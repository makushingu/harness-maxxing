# Technical changes (maintainers)

Private, technical counterpart of `CHANGELOG.md`. `CHANGELOG.md` is **public**: written for users
(what changes for them, plain language), shown in the app ("What's new" after an update) and by
`maxxing update`. This file is for us: API, data formats, migrations, internals, gotchas. It is never
shown in the product. Newest first, same version headings as `CHANGELOG.md`.

## Unreleased

## 2.0.0-alpha.175 - 2026-11-27

- UI check: `scripts/ui-check.sh [--only a,b] [--list] [--shots DIR]` runs `web/e2e/check.py`, 21 journeys in a real Chromium (Python Playwright brought by `uv run --with playwright==1.56.0`, nothing added to `web/package.json`; browser = `MAXXING_E2E_CHROME`, else `<state>/tools/browsers/chromium-*`, else `~/.cache/ms-playwright`) against the committed `web/dist` served by `web/mock/server.mjs` on a free port (`MOCK_FEATURES=all`; `MAXXING_E2E_DIST` = another build). Every page and every Settings section (ids read from `pages/settings/sections.ts`) on a computer and a phone, in English and French, must give no JavaScript error, no API 5xx, not the not-found screen (title = `error.notFound` of `src/i18n/??.ts`), text in `<main>`, and on the phone nothing wider than the screen; plus guide, setup, login, onboarding, session (send, draft kept by a reload, phone), palette, dark / light, a setting saved, Files, Team, sidebar, sign-out. Exit 0 / 1 (a journey failed) / 2 (could not run). About 3 min 30. A new page: add its address to `PAGES`; a new language: nothing (the not-found titles are read from the files). Run it after `npm run build`; the cloud's `publish.py` runs it on the files of the commit it publishes (`--no-ui-check` skips).
- Signed versions (tests `test_secfix_b_signature.py`, `test_cmd_core.py -k signature`). `server/maxxing/release-signers` = git allowed-signers file (one SSH ed25519 key per publisher, `namespaces="git"`). `update_verify_signature` stays `false` by default (to flip to `"stable"` once both publishers' keys are in the file and `publish.py` signs); new value `"stable"`: `cmd_core.signature_mode(branch)` = `on` (true), `auto` ("stable" and the branch is `stable`), `off`. `cmd_update`: fetches `+refs/tags/v*`, then `verify_target()` tries `-c gpg.ssh.allowedSignersFile=<SIGNERS>` (the installed file, before any checkout) then git's own trust. `auto` on a server that cannot check (`signature_unavailable()`: no ssh-keygen, git < 2.34, file missing) = WARN and the update goes on; `on` stops. Doctor `update_signature`: silent when off (`always=True` for Settings -> Security). Rollout: the version shipping this is installed unchecked by older servers; every later stable version MUST carry a signed tag (cloud `publish.py sign_tag`, before `stable` moves, verified against origin/stable's key file). Key rotation = a signed version that edits the file.
- GHSA-942m-233g-9pmw: `gitsafe._filter_overrides` no longer caches (the stamp was the mtime of .git/config, which the writer can put back; a `.git` file had no stamp); an unreadable config raises `GitError(500, git_failed)`. GHSA-m4p9-j9q8-j8x3: `uploads.UploadGuard` also takes `DELETE` (BodyLimit left multipart DELETE to it). `backup._keep_local_rules` also covers `projects/*/groups/*/group.json` (`_GROUP_RULES`; a new group gets `trust_members: false`, no `limits`). GHSA-r5wh-pw6w-8xmc, GHSA-2xvh-vvvv-j7fv, GHSA-8q3x-5xw7-6w4f were closed by the restore fixes of the audit (tests `test_secfix_a_backup.py`, `test_backup.py` agents).
- `cmd_core.security_report()` (checks `sign_in`, `permissions`, `secrets_store`, `security`, `update_signature`, `listen`; a check that raises is skipped), `GET /api/system/security`, web `features/auth/SecurityStatus.tsx` (first card of Settings -> Security; server texts in English, as doctor).
- Lots C, D, E of the security plan (tests `test_secfix_c_*.py`, `test_secfix_d_*.py`, `test_secfix_e_packages.py`). **Key scope**: vault entries (`vault`, `vault_files`) take `topics` (list of `projects/<p>` or `projects/<p>/topics/<t>`, max 50, `vault.check_topics` / `in_scope`, segment match); `exposed_env(path)`, `exposed_files_env(path)`, `spawn.auth_env(path=)`, `claude_env(path=)`, `crons._job_env`; helper turns without a path get unscoped keys only; `PUT /api/secrets/{name}` body `topics`, `PUT /api/secret-files/{name}?topics=`; `maxxing keys set|put-file --topics`. Not a wall: a full-access session can still run `maxxing keys get`. **Sealed store**: `<state>/secrets.json.cred` (systemd-creds, `--name=maxxing-secrets --with-key=auto`, 1 MiB max) is the store when it exists; `config.load_secrets` decrypts once per (inode, mtime_ns, size), writes re-seal with a round-trip check, `SecretsUnreadable` instead of `{}` and writes refused when it cannot be read; `maxxing keys encrypt|decrypt` (root, never in an agent turn); doctor `secrets_store`; `spawn.protected_paths` and backup `DENY_FILES` know the `.cred` and `signins.json`. Not converted: install.sh `grep '"license_token"'` (pre-a87 archive installs). **Webhook phone key**: stored `sha256:<hex>`, converted at the first call or write; switching such a hook to a signed source needs a new secret. **TOTP**: secrets `totp` {secret, last step, pending} and `recovery_codes` (10 SHA-256), ±1 step, a step never twice, limiter key `2f:<client>`; routes `GET /api/auth/second-factor`, `POST /api/auth/totp`, `/totp/confirm`, `/totp/off`, `/recovery-codes`; `twofactor.start`: no Telegram message when the app is on and Telegram 2FA off, silent challenge; `maxxing 2fa off` turns both off. **Signed-in browsers**: cookie `<ts>.<nonce>.<id>.<hmac>`, `<state>/signins.json` (max 50, seen written once a minute), older cookies valid until `legacy_sessions_off` or a password change, a lost file signs everybody out; `GET /api/auth/devices`, `DELETE /api/auth/devices/{did}`, `POST /api/auth/devices/disconnect-others`; `security.hold_socket` closes terminal / browser / device WebSockets (A5). **Community packages**: `community.py` (`report`, `install`, `<state>/installed.json`), `maxxing community check|install|list`, `maxxing themes install --sha256 --source --yes --read`, `GET /api/community/installed`, `community install` owner-only in `agent_guard`; skills `maxxing-extension`, `maxxing-theme` and the workspace CLAUDE.md template tell Claude to check first. Left for a decision: passkeys (needs the `cryptography` dependency), Telegram 2FA off still asks the password only.
- Lot B, safe defaults (tests `test_secfix_b_defaults.py`). `do_init`: a new install (`not older`) with a working sandbox (`_sandbox_ready`: `agent_guard.ensure_profile()` + `available(fresh=True)`) gets `permission_mode: "sandbox"` in config.json and `permission_mode: bypass` in the `.maxxing.json` of every topic of `projects/system` (`_system_full_access`); `COMPACTION_JOB` carries `permission_mode: bypass`. Doctor check `permissions` (INFO in bypass, OK in sandbox, FAIL when the default is sandbox and it cannot start). `maxxing init --count yes|no` writes `register.count` + `asked: true` (the a94 migration then leaves it alone); install.sh `ANON_COUNT` (ask | 1 | 0), asked on a new install with a terminal, `keep` when config.json exists. Not done: `update_verify_signature` on by default (releases are not signed yet: needs a signing key and `publish.py` signing the tag).
- Tool pins (deps.toml, `scripts/bump-pins.sh`): Scrapling 0.4.15 -> 0.5.1 (`SCRAPLING_BELOW` 0.5 -> 0.6; Playwright 1.64.1 / Patchright 1.64.4 on Chromium 1248), Remotion 4.0.534 -> 4.0.547, uv 0.13.10, Node.js 22.23.5, Claude Code first install 2.1.326. `bump-pins.sh` now bumps Remotion too (latest `REMOTION_MAJOR`, every `remotion` / `@remotion/*` of templates/remotion/package.json, lock by `npm install --package-lock-only`). New `scripts/check-tools.sh`: installs the pinned Scrapling lock, Chromium, Remotion into a temp dir and uses them (extract get / fetch, a still, a PDF); run after every bump. Skill web-scraping and docs 17/22: no `DynamicFetcher` / `stealthy-fetch` (removed in 0.5).
- Audit of 24/11, lot A (tests `test_secfix_a_*.py`, one per finding). Guard: `agent_guard.OWNER_ONLY["jarvis"]`, `OWNER_KEPT` (webhooks list/show/url/calls/call/data, feed read-all refused in agent runs, kept in the owner's conversation), `sandboxed_turn()` falls back to `MAXXING_AGENT` without a unit, `settings()` denies Edit on `locked_paths` for an unsandboxed acceptEdits agent. Agents: `_mode_rank` resolves `""` to the inherited mode, `_put_back_safety` at the end of a manager turn, `OWNER_WAIT_KEPT = 5`, event `agent` carries `hops`. `aside.py`: agent walls on a side question. `resume.RELAY_MARK`. `approvals.summary`: `whole=False` on Cf/Cc characters. `backup`: `backup.include` not restored on hold. Browser: `proxy._body` (one request per plain connection), `_exit_itself`, `_resolve` (own 8-thread executor, 64 pending), `view` refuses every `Target.*` on a foreign targetId and orphan frames, `Target.createTarget` always through `view.new_tab`, wireproxy SOCKS with `Username`/`Password` (file `socks`, 0600), proxy `user:pass@` moved to the vault, NAT64 judged by its IPv4. Webhooks: `SYNC_PER_HOOK = 3`, Stripe `claim_delivery`, CSV cells prefixed with `'`, signed empty body -> empty query, "wait" reply with `CSP: sandbox`. `filesite`: received HTML (mail/team attachments) served with a sandbox CSP. Import: hooks stripped from any SKILL.md, `groups/` skipped, imports defanged in `CLAUDE.local.md`. `security._wide` (IPv6 /48). `auth._check_current`: `trusted=True`. `cmd_core._update_code`: `pinned` SHA for checkout / merge / reset / rebase; `doctor --live` in its own empty folder. `vault.RESERVED` extended; `mcp._expose_refs` skips `MAIL_*_PASSWORD` / `BROWSER_EXIT_*`. `profile_photo`: declared dimensions capped at 4096; ffmpeg thumbnails under `prlimit --as=4G`. `infra._run_capped` (4 MB). Team: 2 of 4 download slots and 25 queued files per sender, slow download dropped. `POST /api/git/pull/review` takes `sha`. Web: `diagram.tsx` (`refuseImages`, `noRemote`), `markdown.tsx` (`PLAIN_BLOCKS`, `loadsAtOnce`), prompt prefill armed in memory by `EditWithClaude.tsx`. Left open (product decisions): V8, V11, V12, V17, V19, A9, A10, A14b, B8, B10, B25, daily byte quota of A12, Tailscale SOCKS of B14.
- Permission mode `sandbox` (`workspace.PERMISSION_MODES`, crons, `api/claude.py`, web `PermissionMode`): a session of a topic (and the owner's conversation with an agent of it) runs `--permission-mode acceptEdits` + `agent_guard.topic_settings(topic, cwd)` merged into `--settings` (Claude Code sandbox: `allowWrite` = topic folder + the separate copy, `denyRead` = `secret_paths()` + `home_wall()`, `denyWrite` = `TOPIC_OWNED`, `allowUnsandboxedCommands: true`, `excludedCommands: maxxing:*` with only `TOPIC_CLI` pre-allowed, `WebFetch(domain:*)` = every host for the sandbox proxy, Edit allowed on the workspace and project memory.md) + the approval tool (`approval_args`): the unsandboxed retry (`dangerouslyDisableSandbox`) and edits outside the topic arrive as approvals ("Bash outside the sandbox: …"). Never bypass: Claude Code lets the retry through without a question there. An agent's run in such a topic keeps its own walls (`sandbox` -> `acceptEdits`). `POST /api/approvals/{id}` `full: true` (with allow, `approvals.sandboxed_topic`): `workspace.set_topic_permission_mode(topic, "bypass")`, applied by the next message (new process: the launch changed); `Approval.full_access` shows the button. Sandbox not available (`agent_guard.available`): the turn stops with `TOPIC_SANDBOX_ERROR`. Not done: default of new installations, keys still in the environment. Team: text selected in one's own bubble was invisible (accent on accent) -> `selection:bg-primary-foreground/35`.
- Memory review (`memory_review.py`, `cmd_memory_review.py`, loop + turn-end listener in `api/memory.py`): one Haiku call without tools (`claude -p --tools ""`) after each agent run (`after_run`: transcript with [DID] / [FAILED] / [GOT] lines, at most one proposal a run, none while `PENDING_MAX` = 3 wait for that agent) and once a day for the topics with >= 3 owner sessions in 14 days and a new one since the last look (`daily`, 10 topics at most: one skill + two rules a topic). Proposals in `<state>/memory_proposals.json` (`proposals`, `learned`, `learned_at`), announced with `feed.post(..., ref="memory:<id>", actions=[accept, refuse])` (source `agents` for an agent, `sessions` for a topic; `feed.HANDLERS["memory"]`). Accept = `apply` (bullet into the level's memory.md, or `<topic>/.claude/skills/<name>/SKILL.md`). Waiting and refused texts are sent back to the model as "already proposed". Modes (`mode()`, `config.json` `memory_review`): absent / true = "auto" - `settle` applies at once, marks the proposal `auto`, announces it with one action `undo` (`undo`: removes the exact line stored in `it["undo"]`, puts the old one back, or deletes the skill's SKILL.md; the proposal becomes `rejected`, so it is sent back as "already proposed"); the brake is then `_waiting` = waiting + written alone in the last 24 h; a skill whose folder exists is never overwritten. `"ask"` = the first behaviour (Accept / Refuse). `false` = off (no UI yet). Not charged to the agent's budget. Tests: `conftest` replaces `memory_review._ask` for every test.

## 2.0.0-alpha.174 - 2026-11-27

- `widgets.activity()` filters `jarvis.hides(path)` like `GET /api/sessions` (Jarvis's backstage sessions were counted as Unread forever); test in test_jarvis (open_makes_its_hidden_folder).

## 2.0.0-alpha.173 - 2026-11-26

- Page lists intro: `useListIntro(id, ready)` + `rise(intro, i)` (lib/presence.ts, `.mx-rise` with --i, first visit per tab like the Sessions tree) and `.mx-rise-kids` (globals.css, --i from :nth-child, flat lists); used by AgentsList, team ChatList, tasks ProjectNav, Jarvis board. Prefetch: `agentsQuery`, `agentGroupsQuery`, `teamQuery`, `jarvisQuery` factories (same keys as the hooks) in pageData (`jarvis` also warms its session + tail); `jarvis` chunk in PAGE_LOADERS, warmed when `jarvis_feature`.

## 2.0.0-alpha.172 - 2026-11-25

- Themes: `ThemePreview` loses its `image` and `wallpaper` props (no `<img>`, no `url()`): the tile is always the drawn
  window, a glass theme's backdrop = `wall-a`/`wall-b` or the accent mix. `preview` stays in `/api/themes` (Community).
  `/api/themes/{id}/file/{name}`: `stale-while-revalidate=604800` added to `max-age=300`.
- Audit fixes (FEU, straight to `main` then merged into `beta`): `agents.continue_in_sessions` under `_continue_mu`
  (check for a copy + creation in one step); `api/system` license loop catches one bad pass, `license.move_due`
  reads a non-number / non-finite `move_tried_at` as never tried; `feedback` encodes the whole prompt with
  `errors="replace"` (folder names with lone surrogates); `register.settings()` and `api/onboarding` read a
  non-dict `register` section as the defaults; `FeedbackDialog` footer `sm:flex-wrap`.

## 2.0.0-alpha.171 - 2026-11-25

- Guide: `language` phase removed from `GuideDialog` (starts at `level`); the cards already use `config.language`, which
  AppShell copies into the UI. Keys `guide.languageDesc` / `guide.languageCurrent` removed.

## 2.0.0-alpha.170 - 2026-11-25

- Guide (FEU): `maxxing/guide.py` + `api/guide.py` (`/api/guide`, `/cards`, `/reset`), state in
  `<state>/guide/guide.json`. Cards = one `claude -p --model opus --tools ""` call per step (worker thread, one at a
  time, queue lost on restart -> shown `failed`, asked again by the UI); output checked (`_clean_card`: known topic or
  `default_topic`, `_BANNED` commands, 1 prompt beginner / 2 intermediate / 3 final). Facts sent: topics, 12 recent
  session titles, agents, pages on, global memory.md (3 KB) and the last IMPORT_REPORT.md (2 KB), both through
  `backup.LEAKS` redaction. UI: `web/src/guide/` (steps.ts ids = `guide.STEPS`, checked by test_guide), spotlight
  helpers moved to `tour/spot.ts`; the old 8-step tour (`tour/steps.ts` STEPS, FinalCard, `tourDone`,
  `mx-tour-pending`) removed, `tour/Tour.tsx` plays showcases only. `data-tour="view-switch"` on the Tabs/Zones switch.
- Push (#185): session meta `push` (absent = on; `false` = muted, kept by a hand-off), `Session.push`, accepted by
  `POST /api/sessions` and `PATCH`; `api/push.rings()` is false for a muted session. UI: `useHasPushDevice()` (any device).
- Backup (#186): `_keep_local_rules` -> `_keep_switched_off`: on a server in use, a local `agent.json` with
  `"enabled": false` stays off, and each local trigger with `"enabled": false` stays off (matched by trigger `id`).
- Sessions: before `--resume`, the runner frees a dead process's claim in `~/.claude/sessions/<pid>.json` (regular
  files only, read capped); a `fresh` turn killed after Claude created its thread is resumed (`--resume`) on
  "already in use" instead of `--session-id` again.
- Feedback: the filter gets the customizations, uncommitted files, extensions and themes of the install; a bug is sent
  unless explained for sure; "Send to the team anyway" is a real button.
- Phone, Tabs view: the tab bar folds only while the message box has focus (folding on scroll looped, dropped).

## 2.0.0-alpha.169 - 2026-11-24

- Browser (FEU): `pool.TURN_END_SLEEP` 15 min; `turn_ended[nav]` set when a session navigator's turn is found dead,
  popped by a new turn; its tabs sleep after the delay (`_sleep_turn_tabs`). Known gap: a turn whose browser tools were
  stopped for idleness (`CHILD_IDLE`) is not recorded, its tabs fall back to the unused-tab rule.
- Team (audit, d80ae9b20): a roster from a remote creator makes one of our contacts a member only if they were already
  in or the roster carries a well-formed pair key for them (`teampeer._key_ok`). Known limit: the key is not verified,
  a creator can still vouch for a contact (who would only see what the creator can relay anyway).
- Uploads (audit, f9aa93047): the request ceiling is `upload_max_mb` x `uploads.REQUEST_FILES` (10) + 1 MB; each file
  is held to `upload_max_mb` by `save_upload`. Routes with smaller limits still check after the body is spooled.
- Search (audit, b36a119b1): `SESSIONS_FRESH_S` 0.5 s, a query within that window of the last session refresh does not
  stat every session again (`_state["sessions_at"]`). `test_group_conversations_are_searched` sets it to 0.
- Sessions: the hover popup of tool lines is gone (`Items.tsx`), the row expands instead.
- Mail: `AccountDialog.tsx` `setPort()` sets `imap_tls` / `smtp_tls` from `PORT_TLS` (SMTP 465 ssl, 587/25 starttls; IMAP 993 ssl, 143 starttls, as `cmd_mail` picks them) when a well-known port is typed; other ports and a later Security choice are left alone. `imap.tls_error()` (used by `open_imap` and `mail.open_smtp`) turns `WRONG_VERSION_NUMBER` with `tls == "ssl"` into "this port expects STARTTLS, not SSL/TLS". Test: `test_ssl_on_a_starttls_port_says_to_pick_starttls`.
- Settings, Extensions group: sections `views` (`ViewsSection`, `Extensions.tsx` kind `views` = `agents_view` or type
  `view`; pages = type `page` only, widgets = type `widget`; a page / widget that also brings a view shows in both with a
  badge) and `themes` (`sections/Themes.tsx`: installed themes from `/api/themes`, in use, `css_state`, warnings count,
  `errors`, New theme = draft in the Harness topic, link to Appearance). `CommunityLink` takes `type` (`?type=`).
- Appearance: cards Theme (`ThemePicker`, tiles with `ThemePreview` for `material` solid / glass then installed themes) -> Options of <theme> (mode, accent, tint, fonts) -> Layout. Store fields unchanged (`material` is the theme). Keys `appearance.theme*`, `appearance.default`, `appearance.solidDesc` / `glassDesc`, `appearance.options*` added; `appearance.colors*`, `appearance.fonts`, `settings.material*` removed; `shell.theme` reads Mode.
- Themes: `maxxing/themes.py` (contract `TOKENS` = CSS variables of globals.css a theme may set, by kind; only ever add,
  renames via `ALIASES`; `load()` cleans values by kind, drops unknown keys, checks text contrast per mode on the effective
  values (`_effective`, built-in levels `_LEVELS` / `_TEXT`) and drops failing pairs then the levels; `install()` copies
  theme.json + named images + README/LICENSE). API `GET /api/themes`, `GET /api/themes/{id}/file/{name}` (api/themes.py).
  CLI `maxxing themes list|check|install|verify|remove|tokens` (cmd_themes.py); `install` / `verify` / `remove` owner-only in agent turns
  (agent_guard `OWNER_SUBS`). Skill `maxxing-theme`. Web: `lib/themes.ts` (`themeLook` -> CSS on
  `html[:not(.dark)|.dark][data-theme-id]`, `<style id="mx-theme">`), store `customTheme` (persisted, painted by index.html
  before the app) + `pickTheme` (base + preset options) / `refreshTheme`; `features/themes/useThemeSync` (AppShell)
  refreshes or drops it from the server list; HtmlWidget resends the theme variables when it changes. Appearance: cards
  Theme (`ThemePicker`: Solid, Glass, installed; `ThemePreview` from the theme's values; Ask Harness -> a draft in the
  Harness topic) -> Options of <theme> (mode fixed for a one-mode theme, accent / background hidden when the theme sets
  `primary` / a surface) -> Layout. Mock: `/api/themes` (nord, sunset). Tests `test_themes.py` (tokens exist in
  globals.css, fonts / accents = catalog, docs list every token). Upgrade note a169: add the `maxxing themes` row,
  the `maxxing-theme` skill row and the Appearance clause of `templates/workspace/CLAUDE.md`, and the `39-themes.md` row
  of the help topic.
- Themes, logo: `logo` / `logo_dark` (png/jpg/webp/avif, `MAX_LOGO` 512 KB, one fills the other; svg refused: it
  could run script when opened at its URL) -> `Theme.logo {light, dark}`, served by `/file/`, copied by `install`. Web:
  `ThemeLook.logo` (`isThemeFile` check, also on the persisted store), `LogoMark` uses it per mode and falls back to the
  product logo on error (signed out: theme files need a session); `applyFavicon(accent, logo)` and index.html set the
  tab icon once the image loads (signed out it 401s: the product icon stays) (manifest / apple-touch icons unchanged).
- Themes, advanced CSS: one `"css"` field in theme.json (string or list of lines, 16 KB), checked by `themes._css`
  (refused whole: url()/image()/element(), at-rules but @media/@supports/@container, `position: fixed`, `<`, `\`,
  unbalanced braces/quotes, control characters incl. CR/FF, `var()` in `position`; comments stripped). `css_state`
  none|on|stale: on while `<theme>/.css-check.json` `{ui, css}` matches `ui_fingerprint()` + the css hash (hash of the served build's `assets/*.css` names, `webbuild.active_dist()`), written by `install` and
  `maxxing themes verify <id>` ⇒ an update that changes the interface's CSS switches it off until Claude verifies it.
  Web: `ThemeLook.extra` (nested in `html[data-theme-id]`, re-checked client side `ADVANCED_OK`), `themeCss()`, store
  `themeCssOff` (per browser, reset by `pickTheme`), index.html paints it too; Appearance Options row "Advanced CSS"
  (switch, or "Ask Harness to check" when stale). `useThemeSync` keeps the look while the theme is in `errors`;
  `install --force` swaps folders (`.old`) instead of delete-then-rename; shadows need balanced parentheses;
  `pickTheme` no longer writes a one-mode theme's mode into the Mode setting (and `load` drops `options.mode` of a
  one-mode theme). Extensions: an extension with a wrong `type` stays in Pages (its error shows). Mock: `nord` css on, `sunset` css stale.
- Session watcher (`service._scan`): a meta file is identified by `(inode, mtime_ns, size)` (`_ident`, as `meta_ident` and `store._cache`), no longer by `mtime_ns` alone: two atomic writes in one tick of the kernel's coarse clock share the mtime, and the second was skipped (an idle session until its next write, a running one until `RUNNING_RECHECK_S`). `_known` / `_damaged` hold that tuple. `tests/test_agent_turn_bus.py` failed about 2 runs in 3 because of it.

## 2.0.0-alpha.168 - 2026-11-24

- Devices: `ask_human` description and skill `maxxing-devices` cover taking over ("let me do it"), not only passwords and codes; the session's Watch line exists only during a turn (`SessionDevices.tsx`), so Claude points to `ask_human` or Settings -> Devices.
- `Pending.cid` (the outbox id sent as `client_id`); `usePending.settle(sid, text, ids)` drops every pending whose `cid` is in the event's `client_ids` (a merged event carries several, its text is the joined texts), else the first same-text one as before. Mock: `MOCK_HOLD_MS` holds an idle session's messages, then starts one merged turn with all their ids.
- Agents avatar: skin `olive`, hair `afro` / `ponytail` / `mohawk` / `buzz` / `bobcut` / `braids` / `pigtails` / `spacebuns` / `swept`, faces `grin` / `cheeky` / `calm` (agents.AVATAR + pixels.ts, appended); `MATTE_SKINS` / `MATTE_SHARE` 0.8 for random characters (`randomAvatar`, `agents.random_skin` in `agents new`); `pixelsOf` splits `head` / `bust` at `NECK`, `animate` (default from 24 px) draws `.mx-px-nod` (head breathes, 6 s; all agent animations slowed for a calm page) and `.mx-px-look` (eyes); asleep (`mood="sleep"`) `.mx-px-snore` (9 s) and two 4x4 `.mx-px-z` rising beside the head (`zzz={false}` in the office, which has its own chip); special characters `SPECIALS` (hair `frog` / `bigbrain` / `chad`, = agents.SPECIAL_HAIR: own body, bust, eyes, blink, asleep; no face/accessory; never random, nor in the name-seeded pick); `pixelsOf().look` = how far the eyes may glance (only onto skin: `--mx-look-l/-r`), the blink stays out of the glance; mouths of 5 faces one row down and `focused` one row shorter: a free row between eyes and mouth and between eyes and fringe. `usePending.setQueued` changes a pending message in place after the send (no re-add once settled); `settle` by text skips messages that carry their own id when the event has ids. `Textarea` autosize pins its parent's `min-height` while it measures. Mock: `/api/jarvis*`, `MOCK_JARVIS_EVENTS`, `MOCK_HOLD_MS`.
- Jarvis reuse and archiving: settings `reuse` and `archive_done` (`jarvis.DEFAULTS`, both True; `SettingsIn`,
  `maxxing jarvis set`), written into its `rules.md` (`RULES` lines Sessions / Finished work) and the skill (§ 2 step
  1, § 3). Session meta `owner_at` (epoch): set by `service.send_message` for a message of source `web` or `telegram`
  with no `relay` (`OWNER_SOURCES`), i.e. typed by the owner. `jarvis_made: true`: set by `cmd_sessions._new` when the
  session reports to Jarvis's board (`_reporting` -> `(True, "")`). `jarvis.close()` archives the session
  (`archived`, `jarvis_archived: true`, item `archived: true`, printed by `work close`) when `_archivable`: setting on,
  `jarvis_made`, no `owner_at`, item without `kind` / `to` / `question`, no other open item for that session, idle, not
  an agent's. `_enqueue` (any non-cron message, which already unarchived) drops `jarvis_archived`.
  `jarvis.topic_sessions(path, days=30)` -> `maxxing sessions list --topic P/T [--days N] [--json]`: sessions of that
  exact path updated in the window, not agents', archived ones only when `jarvis_archived`, newest first, 10 max; rows
  `{id, title, state, updated, archived, started_by_jarvis, owner_wrote, context_tokens, last_answer, reusable,
  why_not}`, `why_not` = `running` (running or queued) | `owner_active` (`owner_at` < 30 min) | `context_full`
  (>= 80 % of the path's `auto_compact_tokens`, else of the model window). Tests `test_jarvis_reuse.py`.
- One card for every message the owner did not type. Log line `mx_user.from` (`runner._sender`, was
  `_relay_from`) = `{kind, title?, path?, session?, reports?: [{id, outcome: done|asks|failed}]}`, kind `session` |
  `agent` (relay from another session's turn; `agent` when its path is an agent's) | `cron` | `feed` | `mail` |
  `group` | `manual` | `cli` | `github` | `system`; `mx_user.shown` = the part of the text for the owner (the rest is
  instructions for Claude). Owner messages (web, Telegram, voice, the owner on an agent's page) have neither.
  `service.send_message` / `create_session(..., sender=, shown=)` (queue item `sender`, `shown`, `_sent_by`: known
  kinds only; a message with a sender never sets `owner_at`); no sender + source `cron` / `cli` / `github` /
  `system`, or a relay without `from`, -> that kind. Senders: `agents.run_sender(trigger, source)` for every run that
  is not the owner's (`_fire`), `crons._sender(job)` (job name), `agent_rooms._group_sender`, `{kind: system}` for
  the memory clean, the update assistant, the browser exit back online and the usage-limit retry. Jarvis: the
  backstage brief is sent with `sender = {kind: agent, title: backstage, path: AGENT_PATH, session: <run>}` and
  `shown = <brief>`, its fallback with `BRIEF_SENDER` (`{kind: cron, title: Morning brief}`); reports carry `shown =
  _report_body()`, `_merge_reports` joins them. `relay.jarvis` is gone (no Jarvis case in the display).
  `normalize` now passes `from` whole (it kept only `session` / `title`, dropping `reports`) and `shown`; lines
  without `kind` = `session`. Web: `pages/sessions/RelayCard.tsx` -> `MessageCard.tsx` (type `RelayFrom` ->
  `MessageFrom`), icon and label per kind (`sessions.from.<kind>` / `<kind>Named`), link to the session, else the
  agent or the group; the outcome dot wraps under the title on narrow screens. Older lines: no `from` + source
  `cron` / `cli` / `github` / `system` / `browser` -> a card; bodies between `<<WORK-x` / `<<BRIEF-x` marks shown;
  reports read from `[Work #N · …]`. `sessions.msg.from` and `sessions.relay.fromJarvis` removed.
- `deps.drop_other_libc(node_modules)`, called by `_up_remotion` after `npm ci`: npm 10 does not store `libc` in
  package-lock.json, so `npm ci` installed both `@rspack/binding-linux-x64-{gnu,musl}` and
  `@remotion/compositor-linux-x64-{gnu,musl}`. On a glibc host (`platform.libc_ver()`) the top-level and scoped
  packages whose `package.json` `libc` excludes glibc are removed (musl or unknown host: nothing removed).
  -88 MB on <state>/tools/remotion (413 -> 325 MB); a render checked after the removal. Applied at the next
  Remotion install or update (a pin or lock change), not to an existing install.
- Webhooks & events (`webhooks.py`, new): automations without AI, one trigger (`in`: `/api/hooks/<token>`, sources
  stripe / shopify / github / generic / phone, GET+POST, multipart files, `filter` events / branch globs, `reply`
  now|wait; `event`: feed / agent / cron with `when`) + one action (`shell` in a transient unit
  `maxxing-hook-<id>-<call>` via `maxxing webhooks run`, request as files + `MAXXING_WEBHOOK_*` / `MAXXING_RESPONSE_FILE`,
  never in the command; `call` httpx with templates, `{{key:NAME}}` vault headers, `X-Harness-Signature`, retries;
  `store` SQLite `data/<id>.db`; `notify` = `feed.post` with `feedhooks.PARSERS`). Store `<state>/webhooks/`
  (`hooks.json` under flock, `calls/<id>.jsonl` last 50 + per-call folders, `spool/`, `feed-pos.json`), secrets in
  secrets.json `webhooks`. Durable queue (record before run, `recover()` at start), per-hook `queue.parallel` /
  `max_waiting` (503 + Retry-After), 120/min, 4 waiting callers, 30 s wait (504). See INTERNALS.md `maxxing.webhooks`.
- API: `/api/webhooks` (list + `feed_hooks` + `https`, create, get, PATCH, DELETE, rotate, secret, test,
  calls, call, replay, data json/csv) in `api/webhooks.py` (also the loop: spool every 2 s, feed scan every 5 s,
  `MAXXING_WEBHOOKS_LOOP=0` turns it off); `api/hooks.py` serves a webhooks token first (GET/POST, multipart, wait
  reply), any other token is a feed webhook as before (unchanged URLs, no migration). API.md "Webhooks & events".
- Settings: group `notify` (sections `alerts` = `AlertsSection`, `feed` = `FeedSection`, `telegram`), `voice` in
  `general`; `SECTION_MOVED.notifications` -> `/settings/alerts`; push test URL `/settings/alerts`. Feed webhooks
  (`feedhooks.py`, storage unchanged) are listed and managed on Settings -> Webhooks (`FeedHookRow`: test, secret, new
  URL, delete; an agent's one: link to the agent, no delete) through `/api/feed/hooks`; the feed's add dialog is gone
  (`useCreateHook` removed). Form `features/webhooks/HookEditor.tsx` (`useSaveWebhook`: POST, or PATCH with the whole
  `trigger` / `action` merged over the hook's own). Test sample of a phone hook: `Test sent from the Webhooks page`.
- CLI `cmd_webhooks.py`: `maxxing webhooks list|show|add|edit|describe|on|off|remove|url|rotate|secret|calls|call|test|
  replay|data|run` (`add`/`edit` JSON by `--spec` or stdin, secret on stdin, `test`/`replay` inline).
- `agent_guard`: `WEBHOOKS_OWNER_ONLY` (add, edit, remove, on, off, rotate, secret, replay, test, run, describe) in
  `OWNER_SUBS`: agents may only read hooks.
- `bodylimit`: `/api/hooks/<token>` capped by the hook's own `max_mb` (`webhooks.cap_for_token`), else
  `feedhooks.MAX_BODY`.
- `feed.PRODUCT_SOURCES` gains `webhooks` (the failures of hooks; agents and webhooks cannot post as it); feed events of
  that source and with `hops >= 3` never start event hooks; `notify` from an event carries `hops + 1`.
- Emitters: `crons.run_job` (final outcome, not before a retry) and `agents.on_turn_end` (automatic runs only, next to
  `chain_after`) call `webhooks.emit()`, which writes the spool only when an enabled event hook listens.
- Extensions: `ctx["webhook_data"](id_or_name, after=0, limit=100)` -> the rows of a store hook.
- Skill `maxxing-webhooks` (new); `maxxing-feed`, `maxxing-cron`, `maxxing-agents`, `maxxing-extension` point to it;
  workspace CLAUDE.md template (CLI table, skills table, "Use what Harness already has"), the `help` topic index and
  the Jarvis skill list it. User docs `37-webhooks.md`, `38-events.md`; `08-crons`, `24-feed`, `30-agents`,
  `14-skills`, `17-cli-reference`, `01-welcome`, README updated. Tests `tests/test_webhooks.py`.
- Mentions: new kind `jarvis` (`mentions.KINDS`, `MentionKind`, `ChipKind`): `candidates()` offers one row
  `{kind: jarvis, ref: jarvis, label: Jarvis, state}` first when `jarvis.feature_on()` (not from one of its own
  conversations) and drops every session under `projects/jarvis` from the sessions; `resolve()` gives the command
  `maxxing sessions send jarvis`. `service.relay_message` (`_jarvis_target`): `to` = `jarvis` -> its current
  conversation (made when none), a past conversation's id -> the current one (`jarvis.current_for`). Composer: the
  group `@jarvis` has no title (`SlashMenu.groupTitle` returns "" -> no header), chip/route `/jarvis`, Sparkles icon.

## 2.0.0-alpha.167 - 2026-11-24

- `agent_guard.check_cli`: for `heavy`, a `-h`/`--help` after the command's first word is the command's (REMAINDER),
  not help: the checks run (it ran as root outside the sandbox).
- `cmd_agents` export: `--output` refused when `_turn()["path"]` (an agent turn); stdout stays.
- `gitsafe.SAFE_GIT`: `-c diff.ignoreSubmodules=all -c submodule.recurse=false` (a submodule's own
  `.git/modules/<sub>/config` filters ran on `status`; `_filter_overrides` only sees the main repo).
- `backup._apply` hold: `_keep_local_rules` keeps the local `SECURITY_FIELDS` + `SECURITY_LIMITS` of `agent.json` and
  `permission_mode`/`allowed_tools`/`browser`/`devices` of `.maxxing.json` (new agent -> `enabled: false`, new folder
  -> rules dropped), reported in `held["rules"]`; `_hold_new_jobs` only trusts local jobs that are enabled;
  `extensions.disabled` = union of the saved list, the current one and the held extensions.

## 2.0.0-alpha.166 - 2026-11-23

- `openSync.ts`: ids shared on a phone in Zones too (`sync.ids` and the `active` dependency removed; base no longer
  dropped when the phone leaves Tabs). Front: `sync.mine` = the session in front here at the last agreement; `flush`
  sends `front` only when it changed here since (`f !== sync.mine && f !== sync.front`), so a front of another device
  that is not open here is no longer answered with ours (it undid a link on the phone). `view` keeps `mine` = `before`
  while a change made here is still to send. POST answers go through `sent()`: `setQueryData(qk.openSessions)` when
  newer, so a remounted page no longer applies the older cached GET (it brought the previous front back).
- `pages/sessions/index.tsx` State -> URL (desktop): reads `useSessionsUI.getState()` instead of the rendered
  `focusedCol`/`cols`: on a fresh load with `?session=X`, the URL effect's `openSession(X)` of the same pass is no
  longer overwritten by the persisted front (which then came back through the URL effect).
- `Composer.tsx`: `autoFocus` focuses only if `focused === colKey` when it runs (the composer mounts after the
  session data: the last column to load stole the front in Zones).

## 2.0.0-alpha.165 - 2026-11-23

- Harness Link 0.1.1 (`server/maxxing/link.json`, release `link-v0.1.1`): Android main screen redesigned (`LogoView.kt`
  draws the LINK logo of `link/console.go` cell by cell, `activity_main.xml` cards, `colors`/`themes`/`dimens`, status
  dot drawables), `versionCode` 2 / `versionName` 0.1.1. Desktop binaries rebuilt with VERSION=0.1.1, code unchanged.
- Devices, Add a device -> Android: an APK button under the QR code (`devices-add-apk`) links to the invite's
  `downloads.android` (`/api/devices/download/android?code=`, the personalised APK); texts `devices.add.apk` / `.apkHelp`.
- `sessions/opened.py`: `open_sessions.json` also keeps `tabs` (bool) and `front` (session id), set by `POST /api/sessions/open
  {tabs?, front?}` (a change bumps `rev`, same value = no rev); keys absent until a browser sends them. `openSync.ts`:
  sends the mode / focused session when they change here (debounced with the cols), applies the other device's unless
  changed here since the last agreement (`sync.tabs` / `sync.front`, `sync.start` = front at mount so a link is not
  undone); the query runs on a phone in Zones too (ids still shared only in tabs view). Phone: `/sessions` with nothing
  on screen waits for the shared list and opens its `front`; a front applied while a session is shown updates the URL.
- Phone: `ViewSwitch` (now `className`-able, `pointer-coarse:size-10`) in the `mobile` session header and the mobile new-session
  header; `MobileOverlay` gives the chips when `tabs` (was `cols.length > 1` in both modes), swipe still on `several`.
- Slimming pass (no behaviour change, ~-2 000 lines): dead code removed across server, web and Harness Link (e.g.
  Telegram health watcher superseded by feed alerts, `crons._run_claude`, `SessionPreviewCard`, `UsageIndicator`,
  `FilePreview`, unused ui parts and hooks), duplicates merged (`security.secret_key`, `vault.set_note_expose`,
  shared OSV lookup in `depcheck`/`deps`, one `LiveTokens` class for browser/devices live views, `useDebounced`,
  `STATUS_TONE`), 80 unused i18n keys and 3 unused Radix packages dropped. `maxxing team send --file` reserves the
  target name atomically (`reserve_path`); `imap._date` tolerates a malformed server date.
- `FeedSettings` source row: the name column is `flex-1 basis-40` (was `flex-1`, basis 0): the `flex-wrap` row now
  wraps the `w-44` rule select under the name below ~22 rem instead of truncating the name; guarded by
  `test_web_mobile.py::test_a_notification_source_keeps_its_name_readable_on_a_phone`.
- Settings -> Memory, memory files table: the path cell adds `max-md:whitespace-normal max-md:[overflow-wrap:anywhere]`
  to `truncate` (the `title` is unreachable on touch); guarded by
  `test_web_mobile.py::test_the_memory_files_list_shows_whole_paths_on_a_phone`.
- Mail attachments in the file viewer: `POST /api/mail/{id}/attachments/view` (`imap.attachments_of`, one fetch)
  copies them to `<workspace>/mail/attachments/<id>/<folder hash>-<uid>/<index>/<name>` (rewritten at each view, dirs
  older than a day pruned; `409 outside` when the workspace is not under the files root: `MessageView` then opens /
  downloads as before for the rest of the page's life). Composer chips (`AttachmentChip`, all `MessageBox`es) open
  the uploaded file in the viewer (`list` = the uploaded files of the message). Test:
  `test_mail_connection.py::test_attachments_open_in_the_file_viewer`.
- Jarvis (`jarvis.py`, `api/jarvis.py`, `cmd_jarvis.py`, page `web/src/pages/jarvis`): config `jarvis_feature` (off) and
  `jarvis` (DEFAULTS: model, root, ask_first, internals, daily, brief, dream). Its folder is the reserved project
  `projects/jarvis` (marker `"system": "jarvis"` in its `.maxxing.json`; an owner's project of that name is never taken,
  `create_project("jarvis")` is refused), topic `main` in mode bypass, from `templates/jarvis/` (CLAUDE.md and
  `.claude/` kept up to date by each version, the rest only when missing; `rules.md` written from the settings;
  `brain/**` added to `backup.include`). Hidden unless `internals`: `workspace.tree()`, `list_topics()`,
  `GET /api/sessions` without `path`, `search.search()` (`jarvis.hides`).
- State `<state>/jarvis/state.json` (current conversation, past ones, last brief / night pass, digest mark) and the
  work board `<state>/jarvis/work.json` (`{next, items: [{id, session, path, title, brief, state, ...}]}`, 300 kept).
  `maxxing sessions new|send` from a turn of Jarvis's conversation (or with `--report-to me|<session>` from any turn)
  registers the target session; `service.on_turn_end` -> `jarvis.on_turn_end` reports each ended turn (queue empty,
  not a turn the owner typed) into the conversation as a relayed message (`relay.report`, hops = the work's + 1).
  `maxxing agents run` from Jarvis registers the run's session too. Sessions it starts get mode bypass when `root`.
- Server loop (`api/jarvis.py`, 30 s): `jarvis.tick` sends the morning brief (a new conversation when `daily`) and
  starts the night pass (a separate session, skill `jarvis-dream`, `maxxing jarvis digest [--mark]`) once a day after
  their local time. API `GET /api/jarvis`, `POST /open|/new|/brief|/dream|/work/{ref}/close`, `PUT /settings`; bus
  topic `jarvis`. New CLI `maxxing jarvis …` and `maxxing topics list|new`. The scheduled night pass runs on
  `dream_model` (default `sonnet`) and is skipped when no session, memory.md or tasks.json moved since the last mark
  (`jarvis.quiet_since`). `SessionColumn own`: no session header (title, place, options window), no fork, archive,
  delete or terminal (Jarvis's page).
- Jarvis setting `compact_tokens` (default 150000; 0 = the server's; 100k/150k/200k/300k): `config.session_config(cfg,
  path)` gives its conversation's turns their own `auto_compact_tokens` (idle and smart-resume thresholds capped by
  it, `CLAUDE_CODE_AUTO_COMPACT_WINDOW` from it); `Session.compact_tokens` (null elsewhere) feeds the composer gauge.
- `relay_message(..., short=True)` (`maxxing sessions new|send` that reports back): `relay.short` makes
  `runner.build_prompt` append `SHORT_ANSWER_NOTE` (final answer of 6 lines at most, the long parts in a file; not
  displayed). The skill `jarvis` no longer asks for the 5-line report itself.
- Jarvis setting `telegram` (`off` | `important` (default) | `all`): `jarvis.rings(session)` decides for its
  conversation in `telegram/gateway.rings` (the session's bell is not used): `important` = a turn from the brief
  (`source` cron), a failed turn, or an answer that ends on a question; never a turn from Telegram, a summary or the
  night pass. `finished_message` of Jarvis: title "Jarvis", its whole last answer (`jarvis.last_answer`, 2500
  characters), link `/jarvis`.
- Jarvis's templates are rendered with `cmd_core.template_vars` (+ `{{SKILLS_DIR}}`); its CLAUDE.md says where
  Harness's commands, skills and docs are; skill `jarvis` § 4 = rules to create projects, topics and agents.
- Jarvis page: Work panel hidden/shown (`mx.jarvis.workOpen`) and resized (`mx.jarvis.workWidth`, `ResizeEdge
  edge="left"`, new prop), settings in a `Dialog` (`JarvisSettingsDialog`) instead of a popover.
- Jarvis's backstage agent `projects/jarvis/topics/main/agents/backstage` (`jarvis._ensure_agent`: made at `ensure`,
  role from `templates/jarvis/agent/CLAUDE.md`, model = `dream_model`, `silent`, $3/day): the night pass is
  `agents.fire(AGENT_PATH, prompt=DREAM_TEXT)`; the brief opens the new conversation, fires the agent with
  `PREPARE_TEXT` and registers a board item `kind: brief` (hidden from `JarvisStatus.work` unless `internals`); its end
  sends `[Morning brief]` + the prepared text into the conversation (source cron), else Jarvis makes it itself.
  `agents.list_agents` leaves out Jarvis's project when it is hidden (`jarvis.hides`).
- `jarvis._asks` ignores links, code and inline code, and reads the last two lines only. `jarvis.current_for`:
  `telegram/gateway.bound` sends a reply to a past conversation of Jarvis to its current one; `rings` and
  `finished_message` run off the gateway loop. TimeField saves 0.5 s after a complete time (and when the window
  closes). Composer placeholder of Jarvis's page: `jarvis.placeholder`.
- Web Push (#167): `maxxing/webpush.py` (VAPID/ES256 on P-256 in pure Python, RFC 6979 nonce, empty pushes, devices + key
  pair in `webpush.json` 0600, in-memory queue, allowed push hosts, no redirect followed) and `api/push.py` (`/api/push/*`,
  API.md#push; `startup()` registers a turn-end callback with the Telegram bell's rule, for every session). `web/sw/sw.js`:
  `push` (POST `/api/push/pending`, one notification per session, tag `mx-session-<id>` = the in-page one, so no
  double; a visible focused window skips it except on iOS where every push must show one) and `notificationclick`.
  `features/notify/{push.ts,PushSettings.tsx}`. `showSystemNotification` falls back to `registration.showNotification`
  when `new Notification()` throws (Android). Tests: `test_webpush.py`.
- Dashboard: `widgets._clock()` / `_reset()` format with `_zone()` (config `timezone`) like `day()` and the cron
  cards, and compare with today's date in that zone; they used `datetime.fromtimestamp(at)` (server local time).
  Test: `test_dashboard.py::test_usage_times_in_the_workspace_time_zone`.
- Tests: `test_dashboard.py::test_day_timeline` freezes `widgets.time` at 00:05 of today; it failed every evening
  (after ~21:36 fewer than `MAX_PLANNED` one-minute runs are left, the lane is not dense).
- Thread: "Show earlier" no longer mounts a whole page in one render. Loaded rows: `loadEarlier` sets `growTo` to
  `from - PAGE` and shows `STEP` rows, the progressive first-render effect (one `STEP` slice per idle callback,
  `prevHeight` anchoring) reveals the rest. A page fetched from the server (`items` gain `added` rows at the head):
  `start` moves to `start + added - STEP` during the render and grows back to the old `start` the same way. Longest
  task on a 4 MB log 223 -> 144 ms (945 -> 639 ms at 4x CPU slowdown); on 120 loaded rows 268 -> 117 ms
  (876 -> 400 ms at 4x). Same final rows, reading position kept.
- Dependencies: `npm update` in `web/` and `uv lock --upgrade` in `server/` (minor and patch only). Majors left alone: emojibase-data 18, mermaid 12. `templates/` untouched.

## 2.0.0-alpha.164 - 2026-11-23

- `SessionColumn`: `useSessionStream(place?.hidden ? null : sid)`: a hidden tab (tabs view) closes its SSE. Over
  HTTP/1.1 (local / Tailscale mode, no Caddy h2) one `EventSource` per open tab + `/api/stream` filled the browser's 6
  connections per host and queued `POST /messages` (#178). Shown again, the stream resumes from `get(id).next`.

## 2.0.0-alpha.163 - 2026-11-22

- Agents / Team refactor, no behaviour change: shared helpers (`agents._edit_state`, api `_errors` / `_existing`,
  `cmd_agents._fail` + dispatch table, `agent_rooms._need` / `_at` / `_rewrite`, `agent_guard._deny_secrets` /
  `_deny_edit`, `teampeer._sig` / `_drop_key`); web: `features/agents/chat.tsx` (shared by AgentPage and
  GroupPage), `FormDialog` (Appearance.tsx), Team `TeamDialog` / `Footer` / `Tick` / `nameOf` / `unreadOf`
  (people.tsx), dead `describe_change`, `context`, `_post_shared`, `TriggerChips`, `whereOf` removed.
- `agents.retry_limits`: `retried` saved right after the send (a failing snapshot / budget step resent the paid
  retry each pass). Test: `test_limit_retry.py::test_agent_limit_retry_is_sent_once_when_what_follows_the_send_fails`.
- `team.summarize`: input capped by `team.SUMMARY_CHARS` (100,000, oldest dropped; `count` / `from` match what was
  sent), one at a time per chat (`409 busy`). Tests: `test_team.py::test_the_text_sent_for_a_summary_is_capped`,
  `test_one_summary_of_a_chat_at_a_time`.
- Team composer: uploads use `mutateAsync().then` (React Query only ran the callbacks of the last `mutate()`).

## 2.0.0-alpha.162 - 2026-11-22

- iOS standalone download (`features/files/download.ts` `shareOrOpen`): the file is read up to 120 s
  (`SHARE_READ_MS`, 50 MB cap unchanged, "Preparing" toast after 0.6 s); read within `SHARE_WAIT_MS` -> `navigator.share`
  at once, later (or `NotAllowedError`) -> `toast.action` "File ready" / Save (30 s) whose tap opens the sheet.
  `location.assign` (opens in the app, no way back) only above 50 MB, without file sharing, or on a read error.
  New keys `files.preparing|ready|save`.
- Toaster (`components/ui/toast.tsx`): `bottom-center` on mobile (was `top-center`), `offset` and `mobileOffset`
  (sonner uses the latter under 600 px) = `calc(var(--safe-bottom-ui) + 8px)`. Wrapped in a `contents` div that stops
  `pointerdown` (Radix DismissableLayer listens on the document: a tap on a toast closed the viewer), and
  `[data-sonner-toast]:not([data-visible=false]) { pointer-events: auto }` (a modal sets none on the body).

## 2.0.0-alpha.161 - 2026-11-21

- Thread: `web/src/pages/sessions/toolLabel.ts`. `toolLabel(name, input, t, rel)` -> `{title, detail, kind, danger}`:
  Bash uses `input.description` (only ~1/3 of real Bash calls carry one), else `bashAction(command)` recognises the
  first real command of the line (skips `cd`, env assignments, `env -u`, `sudo`, `timeout`, loop words,
  redirections, here-docs; parses at most `PARSE_MAX` = 4000 chars, split without `\s*` to stay linear). Unknown
  tools (MCP…) return an empty title: the card keeps name + server summary. `isDangerous` (rm -rf, git push --force,
  reset --hard, branch -D, clean -f, DROP/TRUNCATE, DELETE FROM, mkfs, dd) sets the badge, on the full command.
- Grouping: `groupRows` (Thread.tsx) folds runs of >= `GROUP_MIN` (3) tool items where `groupable` (Items.tsx) is
  true into `ToolGroup`, keyed by the first item. `toolKind` is the security boundary of the fold: a Bash line is
  read/search/list/look only if EVERY segment (`&&`, `||`, `;`, `|`) classifies as such; refused outright: `$(`,
  backticks, `<(`/`>(`, newlines, a lone `&`, any `>` except to /dev/null or fd dup, `tee`, `find -delete/-exec/-ok/
  -fprint`, `--output`, `rg --pre`, `sort -o`, `git -c/--config-env/--exec-path`, `sed -i`, longer than PARSE_MAX,
  dangerous. Sub-agents and background tasks never group.
- `RunningRow` shows the label of the pending tool instead of `use.summary`.
- i18n: namespace `tl` in the on-demand group `tlabel` (not declared on the sessions route: it would overflow the
  first-load dictionary budget; listed in ON_DEMAND of test_web_i18n_groups).

## 2.0.0-alpha.160 - 2026-11-21

- Tests: the bare-token fixture of `test_mcp_safety.py` is built by concatenation, so the leak scanners of the
  maintainers' push hooks no longer take it for a live key. `CHANGELOG.md`: one Fixed section in Unreleased.
- Cleanup: `deps.run_lock` (flock on `tools/deps-run.lock`, not deps.lock that `write_record` takes inside an
  update) wraps `deps.update` and a real `deps.clean`; a clean during an update raises `deps.Busy` (row error in
  Settings, `deps clean` prints "skipped" and exits 0). Caches: `_in_use` reads /proc (cmdline, cwd, exe) and
  keeps the uv cache and each `~/.npm/_npx/<hash>` a process runs from. `tmp/uploads` (upload spool) is kept.
  Journal estimate capped at the archived files (`JOURNAL_DIRS`), the only ones `--vacuum-size` removes. New
  part `previews` (off by default): `state/videos/*.mp4` not played in `COPY_KEEP_S` (never `.part.mp4`) and
  `state/thumbs/*.webp`.
- MessageBox (sessions, agents, groups, Team): a mousedown on the box outside its own controls (button, link, field,
  `[role]`, attachments strip) focuses the textarea, caret at the end, with `preventDefault` (no stray selection).
- Composer uploads: in-flight uploads live in `pages/sessions/uploads.ts` (per draft key, outside the component), no
  longer aborted on unmount. A remounted composer shows them again (`uploadsOf`) and follows them (`onUploads`); a
  file that finishes with no composer open on its draft is written to the stored draft (`saveAtts`). The draft key
  change moves them (`moveUploads`).
  `features/agents/attach.tsx` (agents, groups) uses the same store; a box without a draft key still cancels its
  uploads when it goes away.
- Sessions, mark all as read: `useMarkAllRead` (lib/queries/sessions.ts) posts `/seen` for each unread session, with
  the optimistic patch of the list, each session and the topic counters (unread, errors). Tree: the double tick in
  `ListHeader` (all unread live sessions) and `MarkAllReadItem` in the project / topic menus (right click, ⋯,
  drill-down). No new route.
- Search: `search.search` ranks first (bm25 only, best rowid per kind/ref), then runs `snippet()` on the shown rows
  only (`rowid IN (...)`, at most `limit`). `snippet()` re-tokenizes the whole text, so it ran on every matching row
  before (up to `RANK_MAX`): 114-162 ms -> 13-19 ms for 3-letter prefixes on a 4,700-item index, same results.
- Compaction: no `seed` queue item after a summary turn any more. `Runner._post` stores the seed in the session meta
  (`seed`, with the new `csid` and `fresh`) and resets `context_tokens` to `base_tokens`; `Runner.turn` gives it to the
  next item as `preface` and drops it once the thread exists (`saw_init`). A compacted session therefore counts one
  turn less (turn + summary, no third). Hand-off unchanged (`seed` item in the new session).
- Viewer comments: `features/files/docComments.tsx` (zustand, localStorage `mx-doc-comments`, per session). The session
  is the thread the file was opened from (`data-sid` on `[data-thread]`, set in `FilePreview.show`, reset when the
  viewer closes). Passages marked with the CSS Custom Highlight API (`::highlight(mx-doc-comment)`), sent with
  `useSendMessage` as one message. Viewer bar: copy / download / Files / parent folder only in the ⋮ menu (all sizes;
  test ids `viewer-download`, `viewer-open-files`, `viewer-zip` gone, `viewer-more-download` stays).
- Memory: `memory.DEFAULT_MAX_LINES` 200 -> 100 (10 KB). Only installs without `memory_max_lines` in config.json
  follow it; the next compaction shrinks every memory.md over 100 lines / 10 KB. Token test with Romain (11-20).
- Badges: setting `nav_badges_hidden` (routes among `api/settings.BADGE_PAGES` = `/`, `/sessions`, `/team`, `/agents`;
  default `[]`, restored from a backup), Settings -> Features -> Badges (`BadgesPicker` in `sections/Features.tsx`),
  read by `nav.useBadgeOn(route)` in the sidebar entries and the phone ☰ (Sessions). `GET /api/feed` adds
  `unread_errors` (total and per source, `feed._aggregate`): the Home badge takes the `error` tone; the optimistic
  mark-read lowers it too.
- Phone: `MobileOverlay` shows the tabs and the swipe whenever 2+ sessions are open, in both modes (was Tabs mode
  only); the phone header's `TabsToggle` (now useless) is gone, with `tabs.tabs` / `tabs.tabsTip`.

## 2.0.0-alpha.159 - 2026-11-19

- Disk space (Settings -> System): `maxxing/cleanup.py` (`scan`, cached 60 s; `run(parts)` measures each part before
  and after) over five parts `leftovers` / `caches` (`deps.clean`, new `leftovers=` flag to clean the caches alone),
  `journal` (`journalctl --vacuum-size=200M`), `apt` (`apt-get clean`), `trash` (`trash.empty`, off by default);
  system commands go through `cleanup._sh`, stubbed in every test by `conftest`. Routes `GET/POST
  /api/system/cleanup` (API.md). `DiskCard` + `CleanupDialog` in `System.tsx`; "Clean up with Claude" =
  `draftUrl(useHarnessTopic(), t('system.cleanupPrompt'))`.
- Sessions: `DiffView` (`pages/sessions/Items.tsx`, the inline Edit / Write diff) wraps under `md`: rows drop
  `min-w-max` (`max-md:min-w-0`), the text span is `max-md:whitespace-pre-wrap [overflow-wrap:anywhere]`. Desktop
  keeps `whitespace-pre` + horizontal scroll. Test: `test_web_mobile.py::test_an_inline_edit_diff_wraps_its_lines_on_a_phone`.
- Files (#151): touch with no file open renders `PageList` `inline` (the listing is the page, no viewer section,
  the "Open the folder" button of the empty state removed); `PageList` in place closes the drawer's `list` level
  (it would be empty). Composer (#148): the right group of `MessageBox` wraps.
- Settings (PR #156 of Anthony14FR): route `settings/:section?` (was a redirect for `settings`); `SettingsRoute`
  renders `SettingsList` (groups of `SETTINGS_SECTIONS`, 48 px rows) when `useIsMobile()` and no section, else the
  redirect to General. Test in `test_web_mobile.py`.
- Tasks (`pages/tasks/index.tsx`, PR #150 of Anthony14FR): footer hint split in two spans, `tasks.footerHint`
  (`pointer-coarse:hidden`) and new `tasks.footerHintTouch` (en+fr, `hidden pointer-coarse:inline`). Test in
  `test_web_mobile.py`.

## 2.0.0-alpha.158 - 2026-11-19

- Web (from Anthony14FR's PRs #138 #140 #143 #145, rewritten): `useMarkAllSeen()` (`queries/agentGroups.ts`) posts
  `/seen` for each given agent and group (`Promise.all`), patches `thread_unread` / `unread` to 0 at once and
  invalidates both lists; `AgentsList` shows the `agents-mark-all-read` button while `matching` / `matchingRooms`
  (topic + search, whatever the state chip) hold something unread. Tasks: `defaultPrefs()` picks `view: 'list'` when
  `isCompact()`, a saved view wins. Phone session: `MobileOverlay` fills `MobileTabsSlot` only with several columns;
  `MobileTabs` wraps them in `data-kbd-hide data-tabs` (hidden while typing); `globals.css` hides
  `[data-col] [data-kbd-hide]:not([data-tabs])` in landscape below 500 px high on touch screens (the tabs stay, to
  switch session). `DiffRows`: sticky opaque gutter (`diff-gutter`, `bg-popover` under the line's tint), the `@@`
  text in a sticky inline span, the selection ring drawn by `after:` above the gutter.
- Voice: settings `mic` / `call` (default true, `voice.DEFAULTS`, `PUT /api/voice/settings`): `VoiceButton` returns
  null when `mic` is false (unless recording), `VoiceCall` when `call` is false (unless a call is on). Card "Buttons
  of the message box" at the top of Settings -> Voice (texts `vmode.btn.*`, group `vmode`). Composer toolbar: the
  model label and effort hide below `@md` (same breakpoint as the context gauge's ring).
- Web: `Column.tsx` remembers `updated` while the session is shown read, so a "Mark as unread" of the open, focused
  session (same `updated`) is not undone at once; a new answer (new `updated`) is still marked seen.
- Web: session list filters (`Tree.tsx` header): `chip-all` = `Layers` icon (label in `title` / `aria-label`),
  `chip-running` / `chip-unread` = count pills in the `CountBadge` colours (filled when active), hidden at 0 unless
  active; the touch layout is a plain flex row (no segmented grid).
- Web: `useMarkSeen` / `useMarkUnread` take the session (`{id, path, state, archived, unread}`) and patch the
  workspace tree too (topic `unread` / `errors`): the topic, project and sidebar counters follow at once instead of
  after the bus refetch of `/api/sessions` (~1 MB with 1 000 sessions). Mock bench: 340-400 ms -> 65-125 ms.
- Sessions: `POST /api/sessions/{id}/seen` takes an optional `{seen}`; `seen:false` sets meta `marked_unread`
  (public `unread` = finished after `seen_at` or `marked_unread`, never while running), `seen:true` / opening clears
  it. Web: `useMarkUnread` (optimistic, shared `readMark` with `useMarkSeen`), item `unread-toggle` in the session
  row menu of `Tree.tsx` (tree and second bar), texts in the on-demand group `rmark`. Dashboard Activity: unread
  items `ok` (green) instead of `warn`, "Unread" stat tone `ok`. Mock: `/seen` honours `{seen:false}`.
- Files: `/api/files/thumb` takes `h` (min height, bucketed like `w`, in the cache key; ffmpeg `scale=min(iw,
  min(4096,max(w,h*iw/ih)))`). Chat media (box 4:3, h-28) and the attachment strip ask `h=320`, quoted files and
  composer chips `h=160`; viewer placeholder same URL as the chat (`w=320&h=320`); `media.warm` follows. Before: a
  wide picture thumbnailed by width only was stretched in its object-cover box (blurry).
- Web: state lost on unmount (another page unmounts the whole page tree, no keep-alive). Side question
  (`pages/sessions/Aside.tsx`): module zustand store per session, sessionStorage (answered ones only), `api.post`
  instead of a per-call `mutate` callback; `useAskAside` removed. Team composer keyed by chat, draft in
  `mx-draft:team:<chat>`, failed send back via `mutateAsync().catch`. `VoiceButton draftKey`: a transcript that
  arrives after unmount, or a recording cut by unmount (`useRecorder({onUnmount})`), goes to the draft
  (`lib/drafts.ts appendDraft` + `DRAFT_EVENT`, now also heard by `useDraftText` and Team). Composer "Edit queue":
  taken messages land in the draft when the box is gone. Tree delete, Stop, plan approve: `mutateAsync` (follow-ups
  no longer dropped with the component).
- GitHub: `.github/workflows/cla.yml` removed (the CLA bot failed on every closed pull request: `Branch cla-signatures
  not found`). The CLA stays: the maintainers check the signing comment before merging (CONTRIBUTING.md, CLA.md);
  past signatures stay on the branch `cla-signatures`.
- Dependencies: `npm update` in `web/` and `uv lock --upgrade` in `server/` (lockfiles only, ranges unchanged;
  majors left out: mermaid 12, emojibase-data 18). Replaces PRs #107 #110 #112 #116 #117 #118 #126 #128 #130.
  Vite 8.3.8 now warns about `advancedChunks` (deprecated, use `codeSplitting`) and the extensionless import of
  `./src/i18n/groups` in `vite.config.ts` (native config loader): harmless for now.
- `service.list_sessions` reads the turns waiting for a browser exit once per list (`exits.waiting_by_session()`,
  passed to `public(meta, exits_waiting)`) instead of once per session: each `exits.waiting_for` call built the
  state path through `config.state_dir()` (a `mkdir`) and stat'ed `waiting.json`. Measured on a copy of a real
  state with ~2,000 sessions: 139 ms -> 72 ms per list (warm caches); the tree, the dashboard and @-mentions call it.
  `public(meta)` alone is unchanged. Test: `test_browser.py::test_the_session_list_reads_the_turns_waiting_for_an_exit_once`.
- `agents._session_stats` (behind `list_agents(with_status=True)`, i.e. `GET /api/agents` and `agents.get`) passes
  `exits.waiting_by_session()` to `service.public(meta, exits_waiting)` too, read once per list instead of once per
  agent session (same cost as #119: `config.state_dir()` + stat of `waiting.json` each time). Measured on a copy of a
  real state (25 agents, 222 agent sessions): 46 ms -> 37 ms per list (warm caches). Test:
  `test_agents.py::test_the_agents_list_reads_the_turns_waiting_for_an_exit_once`.
- Usage-limit retry at the reset time: `crons.text_reset()` reads "resets 4pm (UTC)" / "resets 4:30pm" / "resets
  4am" (zone in parentheses, else or unknown UTC; next occurrence, or one passed less than `LIMIT_RESET_GRACE_S` =
  15 min ago) and is the last source of `limit_reset()` (epoch, `claude_auth.limits`, text, then `LIMIT_RETRY_S`).
  `crons.limit_retry_at()` = reset + config `limit_retry_delay_s` (default 60, 0-3600, at least 60 s from now; was a
  fixed +120 s), None past `CATCH_UP_WINDOW_S` or when config `limit_retry` (default true) is false - then a limit
  failure is final. Both keys in `/api/settings` (`400 invalid_limit_retry_delay`), card in Settings -> Usage.
  Agents: `on_turn_end` -> `_plan_limit_retry` stores `<state>/agents/<key>.json` `limit_retry` {at, session,
  attempt} (one per agent, the latest wins; not for group turns, not when the session env has
  `MAXXING_CRON_ID`: the cron's `retry_plan` owns it; at most `crons.MAX_RETRIES` for the same session) and posts a
  `note` (`status: limit_retry`). `agents.retry_limits()` (agents loop, every `FEED_POLL_S`) sends `LIMIT_RETRY_TEXT`
  into the same session once due, through `gate()`: `busy` waits, other reasons drop it with a `skip`; the run
  message has `trigger: "limit-retry"`. Fake Claude: `HITLIMIT`.
- `maxxing agents list` (text output, `cmd_agents._list`) counted each agent's jobs with `agents.cron_jobs(path)`,
  i.e. one `crons.list_jobs()` per agent (jobs.json, runs.jsonl, retries, `next_run` of every job each time): it now
  counts them from one `agents.cron_jobs()` call (`path=None` = every job). Measured on a copy of a real state
  (24 agents, 32 jobs, median of 7, in-process): 286 ms -> 62 ms, same output. Test:
  `test_agents_cli.py::test_list_reads_the_scheduled_jobs_once`.

## 2.0.0-alpha.157 - 2026-11-18

- Global daily budget (`server/maxxing/budget.py`): config `daily_budget_usd` (0 = none, settings route, restorable
  from a backup). `spent_today()` sums `days[today].cost` of the session metas touched in the last 25 h (same basis
  as an agent's `day_cost`; a deleted session takes its cost away). `reached()` gates only automatic work:
  `crons._claude_turn(auto=True)` returns a `skipped` run, `agents.gate()` returns `limit` for a non-owner trigger
  (`SKIP_TEXT`, Telegram `AGENT_REASONS`, web `agents.reason.limit`). The user's turns, the owner's messages to an
  agent or a group (`agent_rooms._start` asks `gate(owner=True)`), "Run now" and shell jobs are never held. `check()` runs after every turn (`service.on_turn_end`, in a
  thread) and after a settings save: feed source `system`, info at 80 % (`dedupe budget:<day>:<usd>:80`), alert at
  100 % (ref `budget:reached`, resolved when work runs again). `GET /api/stats/budget`; mock route added.
- **"After another agent" triggers** (`agents.py` "agent" triggers, contract in `docs/dev/API.md` `Trigger`):
  `{kind: "agent", agent: <path>, on: ok|error|any, match, prompt}` in agent.json (`TRIGGER_KINDS`, `_clean_chain`;
  `clean(..., own=path)` refuses itself; `_new_chain_sources_exist` checks only sources added, so a deleted source
  keeps the trigger inert instead of blocking later saves). `on_turn_end` calls `chain_after(path, text, ok, depth)`
  for every run that is neither the owner's conversation (`mine`) nor a group turn nor a Harness turn; matches go
  into the debouncer with `fire_as="after:<tid>"` (kept in `_feed.json`), `depth + 1` (MAX_DEPTH stops loops) and
  the result framed as outside text (`MAXXING_AGENT_OUTSIDE`). The debouncer now has its own lock (`_mu`):
  `on_turn_end` and the agents loop add / pop from two threads. `remap` rewrites the triggers pointing at a moved
  agent (`_remap_chains`). `trigger_stats` counts the runs an "agent" trigger started; `/test` fires it on the source's
  last result. CLI `maxxing agents after <agent> <other> [--on] [--match] [--prompt]` (owner / manager only, like
  `watch`). Web: `AgentTriggers.tsx` row + `ChainTriggerDialog`, `triggerLabel` "after:". Tests:
  `tests/test_agent_chain.py`.

- **Devices** (`maxxing/devices/`, contract in `docs/dev/API.md` "Devices", `INTERNALS.md` "maxxing.devices"): the
  person's computers and phones run Harness Link (`link/` Go, `android/`), connect out to `WS /api/devices/ws`
  (Bearer device token, protocol v2: `hello`/`paused`/`ok`/`err` up; `shot`, `input`, `tree`, `tap_node`,
  `set_text`, `apps`, `open`, `state`, `unpair` down; `shot` also carries `crop` + `sw`/`sh`, `tree` `sw`/`sh`).
  Pairing: `POST /api/devices/invites` -> 8-char code (15 min, single use, hashed) -> `POST /api/devices/pair`
  (public, 20 wrong codes / 10 min per client then 429) -> candidate until `POST /{id}/confirm` (dropped after
  15 min). Desktop downloads carry a trailer `<json {server, code}><u32 BE len>HMLINK01`; `GET /install/<code>.sh|.ps1`,
  `GET /download/<target>?code=` (it prints each step and a short "How to use it" with the commands; an install command whose code expired or was used answers 200 with a script that
  prints the reason and exits 1: `curl -f` would only print the HTTP status), `GET /link/<code>` (phone page, route added to Caddy's UI routes). Binaries come
  from `server/maxxing/link.json` (GitHub release `link-v<version>`, sha256 checked, cached) or
  `MAXXING_LINK_BIN_DIR`. State `<state>/devices/devices.json` (sha256 of tokens), `actions.jsonl` (typed text kept
  as its length only). The app gets `{"t":"access", ok, mode}` on connect, once accepted and when its mode changes
  (`hub._access`, also from the 3 s ticker for CLI changes): its terminal says "Waiting for your OK" / "Accepted".
  Several screens: `hello.screens` / `hello.display`, device field `display` (`PUT /api/devices/{id} {display}`,
  -1..15) sent as `{"t":"display","i"}`; backends: macOS `CGGetActiveDisplayList` + `screencapture -D`, X11 RandR 1.5
  monitors, Windows `EnumDisplayMonitors` + `MOUSEEVENTF_VIRTUALDESK`. Live-view shots carry `live: true` and the app
  gets `{"t":"watch","on"}` (one line in its terminal instead of one per picture). Claude switches screens itself
  with the MCP tool `screen` (view mode too; refused while the person has the device; clears the coordinate space);
  `devices` lists `i name WxH main`. `store.touch` keeps the last `screens` on the device (field in `Device`), so
  `maxxing devices list` shows them; `maxxing devices screen ID N|main` (the 3 s ticker tells the app).
  Product skill `maxxing-devices` (tools, refusals, CLI); `runner.DEVICES_NOTE` points to it.
- Harness Link desktop runs only in the foreground of a terminal (no login entry; older ones removed at start and by
  the install script, which now `exec`s the app on `/dev/tty` and adds `~/.local/bin` / the user `Path`), with a live
  log (`link/console.go`). Windows binaries are console apps named `harness-link-windows-<arch>.exe`, installed as
  `harness-link.exe`. macOS permissions are named after the terminal app (`TERM_PROGRAM`); an empty `screencapture`
  output is a `permission` error. Hello `note` and device error messages kept up to 1000 characters.
- Turns: `runner.devices_args()` adds the stdio MCP `harness-devices` (`maxxing/devices_mcp.py`, stdlib) only when the
  turn sees a device (`devices.visible()`: device `scope` `["*"]` / `project:<p>` / `agent:<path>`, and for an agent
  its `agent.json` `devices` list; a free agent also sees `agent:<its path>`). It relays to the loopback-only
  `POST /api/devices/mcp/<sid>` with a per-turn token (`<state>/devices/turns/`, cleared at startup). One
  `--allowedTools` per turn: merged into the browser's. View mode exposes only `devices`, `screenshot`, `zoom`,
  `ui_tree`, `ask_human`, `wait`, `screen`. Coordinates = pixels of the last `shot` of that device.
- `ask_human` waits in memory (asyncio future, 10 min, turn liveness checked every 2 s), feed ref `devask:<id>`
  (`feed.HANDLERS`), `Session.device_asks`, agent waiting count. Human input over `WS /api/devices/<id>/live`
  (one-time `POST /live-token`; JPEG frames ~3 fps only while watched, JSON `state`) takes the device; Claude's
  input is refused meanwhile, `release` answers the ask (`done` / `skip`) with the person's note.
- `agent.json` `devices` is a security field (adding waits for the owner's OK, removing applies at once);
  `agent_guard` keeps it owner-only. Settings `devices_feature` (off, restorable), doctor `check_devices`,
  CLI `maxxing devices`, bus topic `devices`, settings section `/settings/devices`, showcase `devices`.
- Removed: "Browser of my PC" (`pcbridge.py`, `api/pc.py`, `pc_tools.json`, `pc_agent.json`, `/api/pc/*`,
  `mcp.has_user_server`, `spawn.ensure_mcp_soon`, web `features/pc`, `lib/queries/pc.ts`); `config.local_port()` /
  `local_host()` and `security.loopback()` moved out of it. The HUD: `MessageIn.hud`, `runner.HUD_PREFACE`, inline
  screen captures (`stdin_payload`, `inline_image`), web `Hud.tsx`, route `/hud`, `ui.hud`; Caddy route `hud` -> `link`.
  The `display-capture=()` Permissions-Policy stays.
- `THIRD_PARTY_NOTICES.md` has an Android section (`scripts/third_party_notices.py` `android_packages()`: the
  `implementation(...)` lines of `android/app/build.gradle.kts`, licenses in `ANDROID_KNOWN`).
- Tabs bar: `useTabIndicator` (`tabMotion.ts`) now places an oval (the chip's width, height and offset) behind the
  chips (`z-0`, chips `relative z-10`, transparent): it glides to the tab picked; the underline is gone. `TabsBar`
  `edge` (phone header): the tablist runs edge to edge with its own `px-3`, the scroll-into-view keeps that padding.
- Session multi-selection (`web/src/pages/sessions/selection.ts`, zustand, not persisted): a plain click on a tree
  row sets the anchor, Ctrl/Cmd/Shift + click picks the rows between, in DOM order of `[data-session-row]` under the
  same `[role=tree]` (the anchor copy nearest to the target when it shows twice: Favorites); Ctrl + click on a
  topic / project row picks its live sessions (`TreeSessions` context = `byPath`). `SelectionBar` (Tree.tsx, computer
  only): open (at most `SHOW_OPEN_MAX` in columns, `PICK_OPEN_MAX` 20 in tabs), close, archive, delete (one confirm,
  N `DELETE /api/sessions/{id}` in parallel); Delete key / Escape on the window when no field, dialog or menu has
  the focus. Strings in their own group `sel`, loaded on the first pick.
- `ConfirmHost`: the action button gets the focus on open (not with `typeToConfirm`), arrows swap the focus between
  both buttons, Enter outside a button / field confirms.
- Workspace topics get `errors` (unread, not archived, `state == "error"`; `workspace._session_stats`); `CountBadge`
  / `CountDot` get the tone `error` (destructive), used for the unread counter of the sidebar, ☰, tree and phone
  rows when `errors > 0`; title "Error - " + `sessions.showUnread` (first-load budget). The mock counts it and its failed session is unread.

- Automatic update (`maxxing.auto_update`): an upgrade note no longer makes the preflight "needs a person"
  (`_simple`): since the notes exist about one version out of two has one, so the first of them stopped the
  automatic update for good (every later target crosses the same note). The update now runs as `maxxing update
  --auto` (new flag, kept as `auto` in `update/after.json`); `smartupdate.after_update()` announces the notes to
  apply in the feed (`auto-update-notes:<version>`), no session is opened. `tick()` keeps every pass in
  `auto-update.json` `last` `{at, result, why?}` (GET /api/system/version `auto_update.last`, line under the switch,
  strings `system.autoLast` / `autoRes.*` / `autoWhy.*`, group `settings`), logs a change of result, looks again
  after `BUSY_POLL_S` (5 min) when the server was busy, posts "Harness is updating" only after the unit started
  (new result `failed`), and dedupes "needs you" per version instead of per commit (one per push on beta).

- "Copy the text" (`web/src/features/files/copyText.tsx`: `useCopyChoices`, `CopyTextButton` for a title bar,
  `CopyTextItems` for a menu; used by `Viewer.tsx`, `FilePreview.tsx`, `pages/files/FileView.tsx`, where the text is
  the editor's, unsaved changes included). Plain text is made in the browser by `features/files/plainText.ts`
  (lazy chunk: `markdownToText` walks the mdast of `unified` + `remark-parse` + `remark-gfm`, `htmlToText` walks a
  `DOMParser` document - nothing of the page runs or loads -, `sheetsToText` gives TSV). `unified` and `remark-parse`
  were already installed through react-markdown; they are now declared in `web/package.json`. New route
  `GET /api/files/pdf/text` (`pdftotext`, at most `PDF_TEXT_MAX` 2 MB then `truncated`; a scan gives an empty text).
  `lib/utils.ts` `copyTextLater(promise)`: a text fetched or converted after the click is handed to the clipboard as
  a `ClipboardItem` promise (Safari only writes during the click), with `copyText` as the fallback. Its strings are
  their own dictionary group (`ctext`): the `files` group is part of the first load of a session, whose budget
  (20,000 bytes, `test_web_first_load`) was full.

- **Dependencies** (issue #104): `server/uv.lock` opentelemetry-api 1.45.1 -> 1.45.2 (GHSA-mf5v-w3w3-f6cg).
  `templates/scrapling/requirements.txt` re-resolved from `scrapling[fetchers,rag]==0.4.15` + `soupsieve>=4.0.0`
  (soupsieve 3.0.3 -> 4.1.1, GHSA-mmhr-3c5m-f64f; also playwright 1.64.0 -> 1.64.1, patchright 1.64.1 -> 1.64.4,
  curl-cffi 0.17.0, new frostwork): the lock hash changes, so `deps update` builds a new venv; Chromium stays on
  revision 1248. Scrapling 0.5 is not taken: it drops `DynamicFetcher` and renames `extract stealthy-fetch` to
  `extract fetch` (skill `web-scraping`, users' scripts). `scripts/bump-pins.sh` keeps it below `SCRAPLING_BELOW`
  (0.5), adds the `SCRAPLING_EXTRA` floors to the compile input, and holds playwright on patchright's minor.
- `deps.toml` uv 0.13.1 -> 0.13.8 (GHSA-hq85-5cpj-mr62, sha256 checked against the release's `sha256.sum`);
  `templates/remotion/package-lock.json` fast-uri 3.1.8 -> 3.1.9 (`npm update fast-uri --package-lock-only`;
  GHSA-333x-w4r6-6crp, -w74x-v6f9-j3xg, -wjr9-j795-jxcr, -xhq7-xmqj-769h). Caddy comes from apt: not pinned here.
- **Chromium for two drivers**: `playwright install` deletes every revision no Playwright install links to,
  Patchright's included, so a lock where they need different revisions (playwright 1.65 / patchright 1.64) left
  `StealthyFetcher` without its browser while `deps update chromium` said "installed". `bump-pins.sh` now
  re-resolves with `playwright==<patchright minor>.*`, and `_up_chromium` raises `DepError` when a revision is
  missing after the installs.
- `maxxing deps check --notify` exits 0 when it found something (the feed reports it): the default job `deps-check`
  ran it and its runs read "Failed (code 1)". Without `--notify` the exit code is unchanged (1 = vulnerable).

## 2.0.0-alpha.156 - 2026-11-15

- Voice mode hardening (Radar check): `tts.synth` waits at most `SYNTH_TIMEOUT_S` (30 s, `select`) for the Piper
  worker, then stops it (`504 tts_timeout`) instead of holding `tts._lock` and the call; `voicecall.settings()`
  resets a non-string value of a hand-edited `voice_call`. Browser: a hang up while a call starts closes what it
  opened (mic, peer connection; `VoiceCall` `attempt` counter, `closed` checks after each await); OpenAI's open
  waits at most 15 s and fails on ICE failure (no reconnection stuck), its level meter's AudioContext is closed;
  Gemini's setup waits at most 15 s, a reconnection resets `muted` / captions, the mic buffer is capped while
  disconnected; a call whose connection cannot be renewed is hung up (`VoiceEvents.ended`).
- Voice mode on an agent's page: `VoiceCall` gets `callKey` (`agent:<path>`, the call's own key for `/call/start`;
  `sid` = `chat_session`, '' before the first message, followed when a new conversation starts) and `stream` (the
  call follows that session's log). `RunIn.call` -> `agents.fire(call=)` -> `send_message` / `create_session(call=)`
  (and kept by `owner_wait`).
- Wording only: `sessions.queue.inject` "Add to task", `sessions.msg.injected` "added to the running task" +
  `sessions.msg.injectedTip` (Items.tsx tooltip); no API change.
- Voice mode (`voicecall.py`, `tts.py`, `tts_worker.py`, `api/voice.py` `/call*` `/tts*` `/said`, web
  `features/voice/{VoiceCall,VoiceCallSettings}.tsx` + `features/voice/call/*`, i18n group `vmode`). Config key
  `voice_call` (see API.md#voice-mode). Design after two tries: (1) a small model that answered and rewrote requests
  (`@ask: <request>`) answered from its own knowledge, rephrased in English and switched language; (2) every
  sentence sent to the session with canned acknowledgements was slow and robotic ("I'm taking it into account" on
  each fragment, sentences cut after 0.9 s of silence). Now: the voice converses (`talker_model`, default sonnet;
  `claude -p --input-format stream-json --include-partial-messages --tools ""` per call, cwd `<state>/claude-titles`)
  and decides with a bare `@ask` / `@stop` line (`reply_parts`: an "@" line is never said, an echo of the bracketed
  lines is dropped); `@ask` hands over `_handover(c)` = the user's own sentences since the last hand-over (earlier
  ones only when they answered a question of the voice, small talk left out, `MAX_PENDING` 4). Each message to the
  voice: `[Work: <state line>]` + `[Language: xx]` + the sentence, or `[Work finished|failed|in progress]`.
  Without a model: `classify` (Whisper hallucinations, noise, stop words after "non / ok / attends", language
  requests = a speak verb right before the language name), `is_echo` (60 % of the words of the sentence the voice was
  saying), `sort` (one language per call; the first sentence is transcribed in "auto" and sets it, `settled`). If the
  voice fails, a sentence is handed over anyway with a phrase of `PHRASES`. Messages carry `call: <lang>`
  (`MessageIn.call`, queue item `call`, kept by `_merged`, `runner.CALL_PREFACE`); said while the session works ->
  `/inject`. Browser (`call/local.ts`), one barge-in behaviour (no `turn_mode`): a sound over the voice ducks it
  (`DUCK_VOLUME` 0.3), 0.8 s of speech well over the echo (`CONFIRM_MS`, `CONFIRM_FRAMES`; `DUCK_MAX_MS` 3 s) pauses
  it, quiet again within `DUCK_QUIET_MS` = it was noise; `empty` (noise, `is_echo`, `_BACKCHANNEL` words said over
  the voice: "ouais", "hm", "ok"...) says the cut sentence again from its start; tap = `interrupt()`. End of a
  sentence after `silence_ms` (default 1800). Nothing new is played while the user speaks or while their transcript
  is pending (`hearing`); a reply not started yet is aborted when the user goes on (the server keeps what was not
  handed over, and a cut reply makes the next message start with "[They went on before your reply ended…]"); ends of turns wait for the voice to be
  free, the end of a stopped turn is not told (`muteNext`). Progress (`VoiceCall.tsx`): every 3 s, when the session
  works, the call did nothing for 15 s (then 25 s) and the log moved: `/turn` `outcome=progress` (`note` = last
  assistant text, `tool`). Cloud (`call/cloud.ts` `Relay`): the provider's transcription is kept (pending) and sorted
  by `/call/sort` (stop, noise); `ask_session()` (no argument) sends the pending words.
  Reconnection: `/call/start` `resume` = a new token for the same call; Gemini's setup has `sessionResumption` (the
  browser keeps the last `sessionResumptionUpdate.newHandle` and reconnects on `goAway` or a close, with the handle,
  without it after a refusal, then with `Relay.recap()` = the last 16 lines); OpenAI reconnects on a failed peer
  connection (or 4 s disconnected) or a closed data channel and is given the recap. A tap on a Gemini call mutes the
  reply under way to its `turnComplete` (Live has no cancel); OpenAI: `response.cancel` + `output_audio_buffer.clear`. Piper (piper-tts, GPL) lives
  in its own venv under `<state>/voice/tts`, run apart; `tts_worker.py` is executed by that venv's Python (`-I`),
  never imported. Cloud tokens only (OpenAI client_secrets, Gemini auth_tokens with the full
  `bidiGenerateContentSetup`, so a client cannot change the instructions or tools); the browser talks to the provider
  directly (WebRTC / WebSocket). Mic capture by ScriptProcessor (an AudioWorklet from a Blob is refused by the app's
  script-src). Not done: approvals by voice, Telegram.
- Voice mode, local: `tts.VOICES` = id -> {model, path, speaker?, lang, name} (several voices in one Piper model,
  e.g. upmc Pierre/Jessica; worker request gains `speaker`; old id `fr_FR-upmc-medium` aliased); `pick_voice` only
  uses the chosen voice for its language. `voice_call.local_speed` (0.8-1.5, default 1.15). The first sentence
  of a call is transcribed in any language and sets the call's language (forced into a wrong one, Whisper
  translates: the interface language is only a guess); then transcribed in the call's language; when the mean `avg_logprob` is below `voice.WRONG_LANGUAGE_LOGPROB` (-0.4; right language about
  -0.2, wrong -0.45 to -0.85 with `small`; `voice.text_language` corrects a French run that copied English), the
  other `call_languages()` (voice setting, browser language sent to `/call/start`, server language, en) are tried and
  the best kept (`transcribe_file(among=...)`; `detect_language` cost +1.3 s on every sentence). Barge-in ("call"
  mode): while speaking, the threshold follows the echo heard by the mic (`max(0.07, floor*2.5, echo*1.6)`, 4 frames)
  instead of a fixed 0.32.
- Web: `features/composer/MessageBox.tsx` = the shared shell of every message box (`MessageBox`: slots `above`, `menu`,
  `top`, `backdrop`, `toolbar`, `actions`, `voice`, `send`, `reason`, `closed`, `boxProps`, `compact`,
  `widthClassName`; `TuckedCard` / `TuckedHead` = the cards tucked under the top of the box, rise and sink, last
  content kept 220 ms; `CloseButton`, `StopButton`). `AttachmentChip` + `Att` moved to `features/composer/AttachmentChip.tsx`
  (re-exported by `pages/sessions/Composer`; `progress < 0` = no progress known, "…"), `insertAtCaret` to
  `features/composer/text.ts` (re-exported by `features/agents/attach`). Users: `pages/sessions/Composer` (no visible
  change), the agent box (`AgentPage` `Composer`: toolbar `ModelPicker` + `CompactGauge`, actions New conversation +
  Stop of the chat session via `useStopSession`, reply = `TuckedCard`; the separate `agent-chat-bar` is gone), the group
  box (`GroupPage`: recipients in `top`, the `@` list in `menu`), the Team box (`team/Chat` `Composer`: poll in
  `toolbar`, reply / edit = `TuckedCard`, `VoiceButton` dictation, Enter = newline on `pointer: coarse` like the other
  boxes). `attach.tsx`: `AttachList` / `AttachButton` removed (the shell draws them).
- Web: `CompactGauge` (`pages/sessions/Widgets.tsx`, replaces `ContextGauge`) in the toolbar of the session and agent
  boxes, removed from the session header. Threshold `compactAt(auto_compact_tokens, window)` mirrors
  `runner._auto_compact` (setting raised to 100k, `resume.fit`: min(limit, max(window - 70k, window / 2))); off = the
  model's window. Wide / narrow from the toolbar's `@container` (`@md`). Tooltip texts `cgauge.*` in the `composer` i18n group.

## 2.0.0-alpha.155 - 2026-11-15

- Web: `lib/updateReload.ts` (`isChunkError`, `reloadForUpdate()`: reload at most once a minute, guard
  `sessionStorage['mx-chunk-reload']`) shared by `vite:preloadError` (main.tsx), `ErrorBoundary.componentDidCatch` and
  `RouteError` (a lazy route whose chunk is gone after an update: React Router caught it before, no reload). The
  chunk fallback is neutral (`Sparkles`, tone default, role status), texts `error.updated` / `updatedDesc` / `updating`.

## 2.0.0-alpha.154 - 2026-11-15

- `agent_guard._probe()` runs its bwrap + nested `unshare --user` in a transient unit (`systemd-run --wait
  --collect`, `spawn.hardening_properties()`), like the turns, unless `MAXXING_SPAWN=direct` or no systemd-run.
  Run in the service process, the install's drop-in `10-hardening.conf` (`ProtectKernelTunables=yes`) made bwrap
  fail on `--proc /proc` ("Can't mount proc"): `available()` said `missing: ["user namespaces"]` on every
  install although turn units, without that hardening, sandboxed fine. Test
  `test_the_sandbox_is_tried_in_a_unit_like_the_turns`.
- `claude_auth.record(..., ends)`: the runner (`res["credential_expires_at"]`) and the test / background check
  (`api/claude.run_test`, `--output-format json`) pass Claude Code's `credential_expires_at` (2.1.318+, ISO date,
  present only with a stored claude.ai sign-in; seen on 2.1.325: `"2026-11-18T21:05:20.730Z"`). Kept as `ends`
  (epoch) in claude-auth.json, only for the `credentials` method; a call that says nothing clears it (older CLI).
  `status()` gains `ends_at`; `ending(status)` gives the local date within `ENDS_WARN_S` (10 days) -> health issue
  `claude_login_ends` (warn, server text, no web change) and doctor `claude_auth` WARN. Follows `_relevant`: after
  the credentials file is rewritten (a token refresh outside a turn, a new login) the date is unknown until the
  next real call.
- `agent_cost.PRICES`: rows `fable-5-2` / `mythos-5-2` (8, 40, 0.2, 10), `fable-5-1` / `mythos-5-1` (10, 50,
  0.25, 12.5), `sonnet-5-5` (cache read 0.1), before the family rows (first match wins). Haiku 5.5 over 100k
  tokens of prompt (5x) is still priced at the low rate.
- `spawn.TUNING_ENV` + `CLAUDE_CODE_SUBAGENT_EFFORT`; `claude_models.FALLBACK` -> `claude-fable-5-2`.

## 2.0.0-alpha.153 - 2026-11-15

- Owner's conversation with an agent (`manager_turn`): `runner` computed its mode with `effective_mode({**meta,
  "permission_mode": ""})`, but `meta.path` is the agent folder, and `workspace.topic_permission_mode` of an agent
  path returns the agent's own mode (`agent.json`). An agent in `acceptEdits` / `default` (all sandboxed agents:
  `agent_guard.mode`) ran its conversation in that mode, without the approval tool (`approvals` False): Bash and
  every MCP tool not in `allowed_tools` were refused ("haven't granted it yet" / "requires approval"). The
  conversation now passes `path = agents.topic_of(path)`: the topic's mode, else the global one (bypass by default).
  Runs unchanged. Test: `test_the_conversation_takes_the_topics_mode_not_the_agents`.
- `agents.MANAGER_FREE`: the manager note of an agent without sandbox now says that what the owner asks needs no
  approval and that its runs keep their settings (`MANAGER_BOX` already said it for a sandboxed one).
- Runner, Claude's input closed too early (messages waiting, inject refused, steer killing the process). Two
  sequences of the real CLI: (A) a `--resume` after a kill first prints the notification of a background task the
  previous process left and runs an empty turn for it (`init`, `result` with `origin.kind` "task-notification",
  `num_turns` 0), THEN the prompt's turn: that first `result` set `turn_done` with no task left -> stdin closed
  before the prompt's turn started; (B) the last background task ends while only tasks ran (`turn_done`): stdin
  closed at `background_tasks_changed: []`, a moment before the `init` of the turn Claude starts by itself, which
  may start new tasks (the process then lives on with a closed input). Now `_Proc.sent()` marks a prompt as owed:
  a "task-notification" result does not end the turn while one is (`own_at`: if no `init` follows within
  `TASK_SETTLE_S`, 8 s, `MAXXING_TASK_SETTLE_S`, the prompt was read inside that turn: over); `_Proc.settle()`
  keeps stdin open `TASK_SETTLE_S` after a tracked task ended or such a result; a queued message is handed to the
  process whenever `turn_done` and stdin is open (no longer only while tasks run). A turn without background
  work ends as before, at once. Fake claude: `STALETASK`, `FAKE_CLAUDE_BG_THEN`, `FAKE_CLAUDE_BG_S_<name>`, the
  own turn's result carries `origin`; tests set `MAXXING_TASK_SETTLE_S=1`. Tests `test_steer_background.py`,
  `test_inject.py`.

## 2.0.0-alpha.152 - 2026-11-15

- Harness Browser: `rules.json` blocks the `DOMStorage` and `Storage` domains (a turn could read or write any
  site's local storage of the shared profile by origin, without opening it; `IndexedDB` / `CacheStorage` were already
  blocked).
- Harness Browser: a profile naming a gone connection no longer makes every `browser._save` fail (`clean_profile`
  no longer checks `exit`; `set_profile(..., new_exit=True)` checks a new value; `ensure_project_profile` copies
  `main`'s as it is, `new_exit=False`). Before, settings, profiles and a project's first profile all failed with 400
  and turns started without the browser.
- Compaction of agents: `store.unattended(m)` = `cron` flag and not a conversation (`env.MAXXING_AGENT_CHAT == "1"` or
  `env.MAXXING_AGENT_GROUP`); `runner._auto_compact`, `runner._idle_compact` and `resume.candidate` use it instead of
  `m["cron"]`. The owner's conversation and a member's group session are created with `cron=True` (no Telegram
  mirror, `agents.tidy`), a flag that only dropped at their 2nd message (`service._enqueue` `reset_cron`): their 1st
  turn was never auto-compacted. Runs keep the flag and are never compacted; the archive rule and
  `telegram.gateway.is_human` still read `cron`.
- `agents.on_turn_end`: a turn whose `last_turn.kind` is in `HARNESS_TURNS` (`compact`, `handoff`, `seed`) is costed
  (`charge_unbilled`) and releases its budget hold, then only drains the owner's waiting messages: no `result` in the
  thread, no `agent_rooms.on_turn_end`, no feed alert, no Telegram (before: the summary and the seed turn's reply were
  posted as two results; in a group, a member's next message queued behind its summary could take the summary as its
  answer). Same filter as `telegram.gateway`. Tests: `tests/test_agent_compact.py`.
- Terminal (`maxxing/terminal.py`): `_signal()` used by `resize` and `_kill`: `os.kill(pid)` while
  `getpgid(pid) == getpgrp()` (`setsid -c` has not run yet: the child is still in the server's group), `killpg`
  after. Before, a terminal closed in its first milliseconds sent SIGHUP + SIGTERM to the server's whole group (seen
  as a full test suite ending silently in `test_terminal.py`).
- Agents benchmark of 2026-11-14 (tests `test_agents_bench_fixes.py`):
  - `agent_guard.available()` runs `_probe()` (bwrap + a nested `unshare --user`) once the binaries are there:
    `missing` gains `apparmor` (Ubuntu's `bwrap-userns-restrict` loaded: its `unpriv_bwrap` child profile denies the
    capabilities Claude Code's `apply-seccomp` needs) or `user namespaces`. `setup()` (`sandbox-setup` only) calls
    `drop_distro_profile()`: link in `/etc/apparmor.d/disable/` + `apparmor_parser -R`. `_bwrap_profile_loaded()`
    matches by name (`:glycin:bwrap` no longer counts).
  - `spawn.upper_memory(cwd, workspace)`: the `memory.md` of the levels above the turn's folder whose `CLAUDE.md`
    imports it, appended to the turn's single `--append-system-prompt` (runner `hint`). Skipped outside the
    workspace, for a file without facts (`_has_facts`: headings, comments, template lines) and when
    `projects[cwd].hasClaudeMdExternalIncludesApproved` is set in `.claude.json` (Claude Code loads them itself).
    We do not set that flag ourselves: Claude Code rewrites the file, and it would also follow any other import.
  - `agent_guard.settings()`: `topic_read()` (`Read(//<topic>/**)`) allowed for sandboxed agents and for the new
    branch "no sandbox, acceptEdits / default" (deny: the topic's `.env`, `topic_edit_denied()` when `writable`;
    allow: `FREE_CLI` = `Bash(maxxing agents:*)`, `Bash(maxxing feed:*)` unless approvals). `add_dirs()` no longer
    needs the sandbox. `check_cli`: `OWNER_ONLY` (`sessions new|send`, `cron run|restore`) refused in an agent turn
    that is not the manager.
  - `agents`: snapshots keep the text of `agent.json` (`agent`, <= 100 kB) and fingerprint `WATCHED_FILES`
    (+ `.mcp.json`, `.claude/settings*.json`); `on_turn_end` -> `_pop_snapshot` / `_changed_since` / `_put_back`
    (not for the manager's turns); the note has `restored: ["agent.json"]`. `owner_at` is now stamped by `_save()`
    (every server write of `agent.json`: webhook, mailbox removal... no longer taken for the run's edit).
  - The waiting queue (`owner_wait` in the agent state) also takes the busy starts of `manual` / `telegram` /
    `agent:*` triggers that are not the owner's message: items with `auto: true`, `text` (cut at `EVENT_MAX`) and
    `depth`; their thread message has `waiting` without `owner` and does not count in `_runs_last_hour`. `fire`
    answers `{started: true, waiting: true}` (CLI: `waiting <path>…`, exit 0). Crons and `wait=True` callers are
    unchanged.
  - `TASK_MAX` = 100 000 characters of `prompt`: reason `too_long` (skip in the thread), `POST …/run` -> 413.
  - `workspace._delete`: `agents.hook_ids()` before the move, `agents.drop_hooks()` after (a restored agent's
    webhook trigger is "dead": `agents webhook` gives it a new URL).
  - `agent_format.parse_md`: `bypassPermissions` -> `acceptEdits`, listed in `ignored`. Templates `uptime`,
    `orders`, `sales`, `mail-sort`: `model: haiku` (`agent_templates.fields`).
  - Left as they are, on purpose: a limit under its minimum is still cut (tested behaviour), any model name is
    accepted (gateways), unknown PATCH fields are ignored, the generic webhook takes plain text, group turns skip a
    busy member.
- Git page: `GitNav` (second sidebar) lists the repositories under each source again (`RepoRow`, a `<Link>` so the
  peeked list and the touch drawer close on a pick); a source head is a plain button that folds its section
  (`mx-git-folded` in localStorage), not a page: `SourceCards` / `LocalRow` / `GithubRow` and `?source=` / `?account=`
  are gone, `/git` without `?repo=` is `GitHome` (one line, plus the connect card or the refused keys when GitHub
  needs them; a button to the list on touch); the refresh button is in `PageList`'s `actions`. No new route; text
  keys `git.pick`, `git.list` added, 7 keys of the cards removed.
  `commitUrl(sha, github, pushed)` (GitGraph.tsx) is the one rule for "this commit is on GitHub" (`pushedShas` for a
  clone): the row's short id, the context menu and `CommitDetail`'s new `url` prop use it.
- Git: `GitSessionDialog` (features/git/NewSession.tsx) starts a session from the Git page or a ` ```git ` block:
  `POST /api/sessions` without a message, then `prefillDraft` (as "Work on this PR" does), so no route is added and
  Code mode is not needed. `GitGraph` takes `clones` (paths on the server) and has the item in its branch / commit
  menu (commits now have the menu without GitHub too); `RepoRow` gets a menu with `useContextMenu({ links: true })`.
  The topic proposed: the one holding a clone, else `mx-git-topic` (localStorage), else the inbox. Text keys
  `git.session.*` (group `git`).
- `gitview.overview()` leaves out the repositories under a `THROWAWAY` folder (`tmp`, `temp`, `scratch`);
  `local_repos()` still finds them (pull request sessions, `codediff.prune`) and `resolve()` opens them by their path.
  `_marker()` skips a `.git` file that is not a `gitdir:` pointer. `github_graph` pages the default branch
  (`page`, 100 a page) up to `limit` and says `truncated` when the last page came back full.
- Agents, owner's conversation (`agents.manager_turn`): `run_settings(manager=True)` returns `sandbox: False`,
  `approvals: False` (no `--permission-prompt-tool`), settings = `agent_guard.chat_settings` for a sandboxed agent
  (no `sandbox` block; `permissions.deny` = Read/Edit of the vault and private paths + Edit of `locked_paths` except
  its CLAUDE.md; its rules hook) else `settings()`; the runner gives it the topic's mode (`effective_mode` without the
  session's `permission_mode`, i.e. not the agent's). `agent_guard.sandboxed_turn()` / `sandboxed_session()` are None
  for it (the `maxxing` CLI limits of a sandboxed turn do not apply; `_manages` still limits `agents` to itself).
  `settings()` lost `manager=` and `MANAGER_SAFE`; `MANAGER_BOX` now says the runs are sandboxed. Runs unchanged.
- CPU priorities (`maxxing/cpu.py`, stdlib only; config `cpu_priorities`, default true; INTERNALS "CPU priorities"):
  `maxxing-live.slice` (CPUWeight/IOWeight 1000) / `maxxing-turns.slice` (100) / `maxxing-jobs.slice` (30, its text =
  `jobs_slice_text` = MemoryMax + weights). `cmd_core.ensure_cpu_slices(jobs)` (init, after `ensure_jobs_slice`; PUT
  /api/settings when `cpu_priorities` changes) writes the two new slices + the server drop-in
  `claude-maxxing.service.d/30-cpu-priority.conf` (`Slice=maxxing-live.slice`, taken at the next restart, never
  restarted) atomically when changed, daemon-reload, then `set-property --runtime` on the slices whose cgroup exists;
  off = weights 100, files kept. Uninstall removes them. Paths: `cpu.SLICE_DIR` (conftest points it to tmp_path for
  every test), `cpu.CGROUP_ROOT`, `cpu.PRESSURE_PATH`.
- Turn units: `spawn._start_unit` adds `cpu.turn_slice_args()` (`--slice maxxing-turns.slice` when on and the slice
  file exists). Claude jobs' turns stay there (not in the jobs slice: its MemoryMax budget is unchanged).
- `cpu.set_level(unit, "live"|"normal"|"background") -> bool`: `systemctl set-property --runtime <unit> CPUWeight=
  IOWeight=`, no-op when off / not root / no systemd (for the watched browser).
- `maxxing heavy CMD…` (`cmd_heavy.py`, registered in `commands.py`): `os.execvp` of `cpu.heavy_argv()` =
  `systemd-run --scope --quiet --collect --slice=maxxing-jobs.slice --unit=maxxing-heavy-[session-<sid8>-|cron-<id>-]<pid>.scope`
  (MAXXING_SESSION / MAXXING_CRON_ID), else `nice -n 10 ionice -c3`; 127 when the command is not found.
  `maxxing video render [DIR] [--id] [--out]` (`cmd_video.render`) = `npx remotion render <entry> <id> <out>` through it.
- GET `/api/system/cpu` = `cpu.snapshot()` (cached 3 s): PSI `some` + top 6 units by cgroup `cpu.stat` `usage_usec`
  delta (previous sample kept in memory, 0.5 s sample when none or older than 30 s; Docker containers merged), named
  by `cpu.describe()` (session title / agent name from the sessions store, job name from crons, heavy scopes,
  `maxxing-br-*`/`maxxing-pc-*` = browser) with their level. Health payload: `cpu_pressure`, `cpu_waiting`
  (avg10 >= 20); issue `cpu_pressure` when `cpu.note_pressure` saw avg60 >= 40 for 10 min (reset after a 5 min gap
  without reading), naming the top unit; it goes to the feed like the others (`health_feed`).
- Doctor `cpu_priorities`: slice files / drop-in out of date -> WARN `maxxing init`; on but the server not yet in its
  slice -> INFO (restart).
- Web: CPU meter of `StatusBlock` = popover `CpuWho` / `CpuPanel` (`useCpu`, every 3 s while open; i18n group
  `cpuwho`), amber + "waiting" when `cpu_waiting`; RAM / disk stay links. `mood.cpuWaiting` before `mood.cpuHot`,
  `mood.issue.cpuPressure`; Settings -> System `CpuCard` (switch); showcase `cpu`.
- Template `CLAUDE.md`: rows `maxxing video … render` and `maxxing heavy` (upgrade note
  `docs/upgrade/2.0.0a150.md`: renumber it if the version is taken). Skill `video-motion-design` and
  the Remotion README render with `maxxing video render`.
- Tests: `test_cpu_priorities.py` (slice texts, init on/off + runtime weights, doctor, turn slice, `set_level`, heavy
  command line + exec, video render, pressure parsing + alert, unit names, cgroup top, endpoint + setting);
  `test_settings.py::test_get_defaults` has `cpu_priorities`.

- Harness Browser (`maxxing/browser/`, never released before: it lived on a research branch; API.md "Harness
  Browser", INTERNALS "maxxing.browser", user doc 33). Config `browser_feature` (default false) + `config.json ->
  browser` = `{ask, wait_min, downloads, idle_min, tab_sleep_min, max_tabs, max_active_profiles (3, 1..8),
  exit_wait_s (180, 0..900), search (google|duckduckgo|bing), profiles: [{id, name, exit: "direct"|<exit id>, on_exit_down:
  wait|vps, project: "" | "projects/<name>"}] (<= 40, `main` always first, not deletable; one per project, see below), exits: [{id, name, type: proxy {url, user} | tailscale
  {node, login_server} | wireguard {}}] (<= 10)}`; `browser.clean_settings(raw, strict)`. Exit secrets in the vault
  `BROWSER_EXIT_<ID>` (`expose: false`). Owners: `browser: {enabled?, profile?}` in a project's / topic's
  `.maxxing.json` (`workspace.folder_browser` / `set_folder_browser`) and agent.json (`agents._clean_browser`,
  `browser` in `SECURITY_FIELDS`: off is safer, the rest is asked); `browser.resolve` = `enabled` topic ->
  project -> true (`SESSIONS_DEFAULT`; an agent's never inherited, false unless set); `SHARED_PROJECTS` (general, system)
  use `main` ("General"): no profile of their own, an older one loses its `project`, `profile` = an agent's own choice when it exists, else its project's.
  **One profile per project** (`project` field): `ensure_project_profile` (from `main`'s exit/on_exit_down,
  named after the project) at the first `active_for`, at `GET /owner` of an enabled folder, and for every project with
  an agent at `GET /api/browser`; `DELETE` refused (`409 project`) while the project exists; `GET /profiles/{pid}` = `{profile, browser, gone, agents, person, temporary (replays.sessions: actions with a `nav` "session:*"), actions, asks}`; ProfileRow adds `gone`, `agents`; `profile: "own"` and a
  project's / topic's `profile` are read as "its project's". `GET /owner` adds `project`, `project_profile`, `sites`.
  **Sites**: a profile has no list (a profile's `web` / `sites` of before are dropped; Chromium policy without
  `URLAllowlist`, no restart on a change). Any public site for every turn and the person, except a sandboxed agent's
  run (not its owner's conversation, which is not sandboxed): `browser.agent_sites(owner)` = its `domains` (None = any
  public site, `[]` = nothing), read once by the runner (`browser_args`, `agent["sandbox"]`) into the turn file
  (`turns/<sid>.json` `sites`; `turns.sites_of`, a file without it reads the agent), then `Turn.sites`: checked on a
  tool's `url` (`Pool.call`), in its `/cdp` relay (`Page.navigate` / `Target.createTarget`) and after each tool call
  (`Pool._keep_to`: a tab of its navigator outside them -> `about:blank`, Claude told; `Watcher.cdp_navigate`). A
  refusal for the list only (`rules.off_domains`) posts a feed event (`browser/domains.py`: source `agents`, ref
  `browsersite:<agent>|<host>`, action `add` -> `domains.add`, dedupe per agent, host and day). Live view:
  `DomainBar` (PATCH the agent's `domains`). `rules.page_refusal` keeps refusing this server, local networks, raw IPs,
  `file:` and browser pages for all. `GET /api/browser`: `navigators()` once, `navs.agents_on(s)` reads each agent
  once (`browser.agent_profile`). Navigator ids: `me`, `agent:<path>`, `session:<sid>` (an old `me-N` tab falls back
  to `me`). Web: `MyBrowser.tsx` (the page without `?live=1`), `EmptyCard`.
- Modules: `exits.py` (exits, `Runtime` up/down state + 30 s watcher, `Tailscale` = own userspace `tailscaled`, `WireGuard` =
  `wireproxy`, units `maxxing-bx-<install>-<eid>`, `test()` via ip-api.com + 2 MB download, `wait_down` / `set_resume` /
  `_resume_waiters`, `feed_action`), `pool.py` (one Chromium per profile, `max_active_profiles`, `exit_ready`, a
  chrome-devtools-mcp per turn; `control[nav]`, `create` one tab at a time per profile, `navigators()`, `move_nav`,
  `drop_nav`, `_close_sessions`: a session's navigator closed after `idle_min` unused), `navs.py` (navigators `me` (its
  profile in `<state>/browser/navigators.json`), `agent:<path>`, `session:<sid>`; one window per navigator: `window.open` from a page of it, else `newWindow`), `live.py` (a `Screen`
  per navigator watched; up to `INFLIGHT` = 3 frames on their way per viewer, `{"t":"got"}` sent on arrival,
  adaptive JPEG quality 30..70 on the queueing (trip minus fastest trip), `?q=auto|high|low`; the tab shown is
  `Target.activateTarget`-ed; `Watcher.dialog` / `chooser` from `Page.javascriptDialogOpening` /
  `fileChooserOpened` (interception on for its sessions), viewer events `{"t":"copy"}` -> `{"t":"copied", text}`,
  `{"t":"dialog", accept, text}`, `{"t":"chooser"}` = cancel; `give_files`), `unit.py` (unit
  `maxxing-br-<install>-<pid>`, `set_level` -> `cpu.set_level`, `cpu.turn_slice_args()`, `--lang` /
  `--accept-lang` from `config.language`, `TZ` from `config.timezone`; `run/<pid>/uploads` emptied at each start), `proxy.py` (upstream through the exit by checked IP, 502 + marked down when it fails),
  `tabs.py` (tabs carry `nav`; `claim` / `assign`; `by` = who opened it), `view.py` (a turn's tools see only their
  navigator: events filtered, foreign auto-attach detached, `getTargets` filtered, foreign targets refused,
  `createTarget` made by the server), `relay.py`, `rules.py`
  (`address(text, engine)`: an address or a search, `SEARCH_ENGINES` google | duckduckgo | bing = settings `search`,
  default google; `DOM.setFileInputFiles` allowed only for files
  under `rules.UPLOAD_ROOTS` = `/mxrun/uploads/` (+ the real folder in direct mode),
  `Page.setInterceptFileChooserDialog` allowed),
  `cdm.py`, `asks.py`, `replays.py`, `turns.py`; `browser_mcp.py` (stdlib, per turn) + `runner.browser_args`.
  Removed v3 notions (research branch only): tab scopes `me` / `topic:` / `project:` / `agent:`, "Share with",
  filtering by scope in the relay, `profile: keep|fresh`, global `web` / `sites`.
- State `<state>/browser/`: `profiles/<pid>/`, `run/<pid>/`, `tabs/<pid>.json`, `actions/<pid>.jsonl`,
  `asks/<id>.json`, `turns/<sid>.json` + `.mcp.json`, `exits/<eid>/`, `waiting.json` (`[{session, owner, exit,
  profile, at, resume}]`); tools `<state>/tools/tailscale-<v>/`, `wireproxy-<v>/` (pinned sha256). Migration
  (`browser.migrate()`, at startup and each profile start): `profiles/harness` -> `profiles/main`, `tabs.json` ->
  `tabs/main.json`; top-level `web` / `sites` dropped.
- Routes (`api/browser.py`): `GET /api/browser`, `PUT /settings`, `POST /setup {exits?}`, `/profiles` (POST, GET / PUT
  / DELETE `{pid}`, `{pid}/open|stop|sleep|forget`, `{pid}/tabs`, `{pid}/tabs/{key}/show`, DELETE `{pid}/tabs/{key}`),
  `{pid}/open {nav?}`, `{pid}/tabs {url?, nav?}`, `{pid}/picture?nav=&w=` (JPEG of that navigator's tab; 204 when not
  running, never starts it), `PUT /navigators/me {profile}`, `{pid}/files?nav=` (multipart `files`, <= 50 MB each: for the page's open file chooser, 409 without one;
  `pool.stage`), `/exits` (POST, PUT / DELETE `{eid}`, `{eid}/test` incl. `direct`, GET / POST `{eid}/tailscale`), GET / PUT
  `/owner` (`inherit: [...]`), `POST /waiting/{sid} {action: resume|retry|dismiss}`, `/asks`, `/live-token`, WS
  `/live?t=&profile=&nav=&q=`, `GET /api/browser` adds `navigators`, loopback `POST /mcp/{sid}` and WS `/cdp/{pid}`. Sessions list: `browser_asks`,
  `browser_exit` (`sessions/service.py`). Feed: ref `browserexit:<eid>` (`feed.HANDLERS`), actions `retry`, `resume`.
- `pool.public` adds `dialog {type, message, default}` and `chooser {multiple}`. Claude's `upload_file`:
  `pool.claude_file` (a file of the turn's topic / project folder, <= 50 MB) copied by `pool.stage` into the uploads
  folder, `filePath` rewritten.
- Exits are checked by themselves while looked at: `GET /api/browser` calls `Runtime.refresh_seen(exits)` - in the
  background, one at a time per exit, an exit not checked for `SEEN_FRESH` (60 s) gets `check()`, and when it is up
  with no good test younger than `RETEST_EVERY` (1 h; a failed one: 60 s) `test(eid, speed=False)` (no 2 MB
  download); `direct` too. Tests persist in `<state>/browser/exit-tests.json`; `exits[].checking` / `direct.checking`.
- CLI `cmd_browser.py`: `maxxing browser enable|disable` (`browser_feature`; `enable` runs `unit.setup` first when
  something is missing, exit 1 and stays off if it still is) | `setup [--exits] | status [--json] | settings [...] [--max-profiles N] |
  profile add|set|rm | exit test ID|direct | set PATH on|off|inherit [--profile ID|own|inherit] | show [--json] |
  forget ID`; `agent_guard.BROWSER_OWNER_ONLY` refuses `set profile forget setup settings enable disable` in agent turns. Skill `maxxing-browser` (turn it on, sign-ins, what to check when its tools are missing, troubleshooting); `BROWSER_NOTE` names Watch and forbids asking for a password in the chat.
- Web: Settings section `browser` (`features/browser/BrowserSettings.tsx`, lazy with its i18n group; `?profile=`,
  `?exit=<id>|new|direct`, `?new=profile`; `?live=1` / `?nav=` / `?session=` = the live view in a window over it);
  `/browser?…` redirects there (`BrowserMoved`, also the links of notifications). My browser = one window for the app
  (`open.ts` `openMyBrowser` / `useMyBrowserOpen`, `MyBrowserWindow` mounted by `AppShell` once asked): the sidebar's
  browser line (shown whenever the feature is on), Ctrl+K `act:browser`, Settings -> Browser. `BrowserWindow` up to
  96vw x 92dvh. No sidebar page any more (`nav.ts`). Files: `features/browser/{BrowserSettings, BrowserPanel, BrowserFeature, ProfileSettings, Exits, SessionBrowser,
  LiveView, QuickMenu, BrowserWindow, MyBrowserWindow, AgentBrowserCard, profiles, open}` (`QuickMenu` = the ⋮ of the live view; picture choice in
  `localStorage` `mx.browser.quality`) (`AgentBrowserCard` in the agent's info panel: a
  picture every 2 s while visible and running); project and topic menus -> **Browser...** (`Tree.tsx`), agent settings section `browser`; sidebar
  line in `HealthIndicator.tsx`. i18n group `browser` (`groups.ts`) loaded with Settings -> Browser, elsewhere on its first
  key (`ON_DEMAND` in `test_web_i18n_groups.py`). Showcase `browser` (Settings -> Features, `data-tour="browser-feature"`).
- Template: help index row `33-browser.md` (upgrade note `docs/upgrade/2.0.0a150.md` step 2).
- Tests: `test_browser.py` (settings and migration, profiles, owners and inheritance, exits + vault, proxy through an
  upstream, waiting for a down exit, live pacing, routes, CLI); `test_settings.py::test_get_defaults` has
  `browser_feature`.

## 2.0.0-alpha.151 - 2026-11-14

- Chips: one component `web/src/features/chips/Chip.tsx` (`Chip`, `ChipData` kinds session/agent/team/group/all/
  command, `findNames`, `findCommand`, `withChips`, `ChipBackdrop`). In a textarea the chip is a backdrop: the same
  text, transparent, with a tint under each span, mirrored from the textarea's computed font/padding/width and scroll;
  the textarea keeps drawing text, caret and selection. Used by the sessions composer (`/` command + picked `@`), the
  agent conversation box (`/`) and the group box (`@handle`, `features/agents/mentions.tsx` now builds on it).
- The `mx_user` log line keeps the resolved mentions (`runner._mentions_shown`: kind, ref, label, group, avatar; never
  the command); the `user` event carries them as `mentions` (`SentMention`), drawn by `ChipText` in `UserMessage`.
  `mentions.resolve` adds the agent's `avatar`; `mentions.candidates` labels Team names with `_plain()` like `resolve`
  (the written `@name` is found again). A sent `/name` is a chip only for a skill of its topic (`ChipText path`).
  Unsent bubbles carry their mentions (`Pending.mentions`).

- Memory: `memory.files()` adds `heavy` (bytes > `max_bytes(limit)` = limit x 1024 / `LINES_PER_KB`, 1 KB for 10
  lines) and `over` is now "too many lines OR too heavy"; `/api/memory` and `maxxing memory --json` add `max_bytes`;
  `compact_prompt` names both limits; skills `memory` (one or two lines per bullet) and `memory-compaction` (weight,
  how to shorten a heavy file). No new setting. Why: Claude Code re-reads the instruction files at each process
  start (`--resume`, attachment `instructions` with `changed: true`, reason `session_start`) and attaches every
  changed file IN FULL; a turn is a new process unless it joins a live one, so each edit of an imported `memory.md`
  costs its whole size in every session of the folder at their next turn. Measured here: 71 KB = +32k tokens per
  edit, three edits between two automatic compactions (130k on a 200k window). No switch for this in the CLI.
- Sessions: the `init` event carries `same: true` when its turn runs in a Claude process that already ran one
  (`runner.py` stamps the raw line `mx_same_proc`, after `clip_event`, from `_Proc.inits`). The page (`log.ts`
  `fold`) marked every running task `interrupted` at each `user` event (true before stream-json input, when a turn
  was a process); it now does it at the `init` that follows a typed message and has no `same` (`turnOpen`, `cut`,
  `headNew` in `LogState`, used by `foldBefore` when the turn straddles two pages). Logs written before have no
  stamp: their tasks read as before. Mock: `same` on the turn of a session with its background agent.
- Runner, reuse of the live process: `launch` differed as soon as `mcp_auto.plan` did (the hint of the system
  prompt lists the servers left out), so a handed-over message got a new process for any drift of the plan. Now
  `proc_core` (the command line built with `NO_PLAN`, + cwd, env, the `mcp_auto` switch) and `proc_plan` are kept
  next to `proc_launch`: same core and `mcp_auto.missing(proc_plan, plan) == []` -> the process stays. `Plan.asked`
  = servers of the pool named by the message or by `mcp_loaded`. A turn that joins a live process (steer too)
  passes `proc_plan` to `_mcp_after`: `given` is what the process has, not what a new one would get.

## 2.0.0-alpha.150 - 2026-11-13

- Documents: `maxxing/documents.py` (stdlib only: zipfile + ElementTree) reads OOXML and ODF: `read(path)` ->
  `{type: text|slides, markdown}` or `{type: sheets, sheets: [{name, rows, truncated}]}`, `media(path, name)` for a
  picture of the package; `Unreadable(unsupported|too_large)`. Guards: XML parts capped, 8 s deadline, DTD refused,
  text escaped, links http(s)/mailto only, pictures png/jpg/gif/webp/bmp only. Routes `GET /api/files/doc`
  (413 / 415) and `/api/files/doc/media`. Web: kind `document` (`kinds.ts`, `isSheets` / `isTextDoc`),
  `features/files/docs.tsx` (`DocView`, `SheetsView`), `MarkdownView` / `MarkdownReader` take `image` (a ref of the
  Markdown -> URL).
- PDF pages: `GET /api/files/pdf` (`{pages, ratio, mtime}`, 415 without poppler / ffmpeg) and `/api/files/pdf/page`
  (`n`, `w` mapped to 640 / 1280 / 2048, WebP cached in `state/thumbs`). `_pdf_thumb` renders through an uncompressed
  TIFF (0.04 s instead of 0.33 s for the PNG; ~0.35 s per page with the WebP). Web: `PdfView` keeps the iframe when
  `navigator.pdfViewerEnabled` and the pointer is fine, else `features/files/pdfPages.tsx` (pages near the screen
  only, zoom 1-4 by pinch / double tap / Ctrl + wheel, the picture asked again at the zoom once the fingers are up,
  `data-zoomed` holds the viewer's swipe); a 415 falls back to the iframe.
- Web, file viewer speed: the viewer's chunk is loaded by `features/files/viewerLoad.ts` (`loadFileViewer`, with
  the `files` words) and mounted by `AppShell` WITHOUT Suspense: React keeps a fallback it has shown for 300 ms
  (even `null`), which delayed every first opening. It is warmed by the last step of `startIdlePrefetch` and by a
  delegated `pointerover` on `[data-mx-file]` / `#mx-file=` links (the chunk only, no request about the path).
  `warmLazy()` (`viewers.tsx`) does the same for CodeMirror and Markdown: warmed when the file opens
  (`warmCodeEditor`, `warmMarkdown`), rendered directly once loaded. `ViewerPane`: a name with a known extension
  (`kind !== 'binary'`) no longer waits for the probe (`eager`): `/read`, `/stat`, `/doc`, `/pdf` leave with the
  listings, and the first answer shows the file (the probe still decides when it says folder or missing). The
  probe's listings seed the stamps (`seedFileStamps`), a stamp asked `within` a folder also seeds the plain one,
  `prefetchMedia` (thumbnail hover) asks the stamp first (`fileStamp`) so it loads the URL the viewer uses.
  `ImageView` fetches the original after the preview only when `canPrefetch()`. `PdfPages` starts from the
  screen's width (it asked the first pages at 2048 then again at 1280 on a phone). Not changed: video Auto quality.

- Web, surface levels (`styles/globals.css`): the surfaces come from one lightness scale per theme (`--l-frame`
  `--l-list` `--l-content` `--l-card` `--l-float` `--l-muted` `--l-accent`) and a hue/chroma pair (`--sf-h`, `--sf-c`;
  `[data-tint='tinted']` only changes the pair). New token `list` (`bg-list`, second bar). Shell classes: `mx-shell`
  (AppShell root = frame), `mx-frame` (sidebar), `mx-list` (second bar), `mx-content` (`#main`: inset panel, 8 px
  margin, `--shadow-panel`, desktop only), `mx-bar` (sticky headers), `mx-glass` (floating layers: popover, dropdown,
  select, dialog, alert dialog, sheet, palette, `/` menu, session preview). Light mode: hover/selected rows on the bars
  rise to white (`--accent` redefined under `.mx-frame, .mx-list`). Sidebar and second bar lost their right border.
- Web, sessions: `TaskBar` (pill above the composer, `data-testid="task-bar"`) removed; `RunningRow` (Thread.tsx)
  shows the running tasks itself through `TasksRunning` (Tasks.tsx, `data-testid="tasks-running"`, same popover,
  `runningTasks()`): the count leads when nothing else is pending or when the pending tool launched one of them,
  otherwise "· N subagents" after the tool (`tasks.short*`). `RunningRow tasks={false}` in `PreviewWorking` (the
  preview lists them already).
- Web, fills: `--fill-1` / `--muted` / `--accent` are now `color-mix` veils of `--foreground` (`--a-fill-1/2/3`:
  3 / 5.5 / 8.5 % light, 3.5 / 6.5 / 10.5 % dark), `--sunken` = `--sidebar` at 60 %; utilities `bg-fill-1`,
  `bg-sunken`. Codemod: `bg-muted/20-30` → `bg-fill-1`, `bg-muted/40-70` and `bg-accent/30-70` → `bg-muted`,
  `bg-card/60` → `bg-card`, `bg-background/40-80` in quiet zones → `bg-sunken` (overlays over text kept). New test
  `test_fills_come_from_the_scale`. `--secondary` stays solid.
- Web, liquid glass (Glass material only): `.mx-lg` (Card, Composer box), `.mx-lg-btn` (button secondary/outline),
  `.mx-lg-pill` (`navRow` active, `Segmented` active); vars `--lg-fill/-sheen/-rim-hi/-rim-lo/-rim-mid/-spec/-drop`;
  the content panel goes to 58 % in glass so the wallpaper shows through the cards.
- Web, material: `useUI().material` = `solid | glass` (localStorage `mx-ui`, mirrored by the `index.html` first-paint
  script as `html[data-material]`), Settings -> Appearance row. Glass = accent wallpaper on `.mx-shell`
  (`--wall-a/-b`), translucent `color-mix` on the classes above, `backdrop-filter` only on `.mx-bar` and `.mx-glass`
  (DESIGN.md rule relaxed for this opt-in; `test_no_backdrop_blur` skips the glass rules of `globals.css`),
  `--glass-edge` inset highlight; disabled under `prefers-reduced-transparency`. Not part of the server-shared look (`/api/settings/look`).
- Web, glass 2nd pass: wallpaper in `--wall`, also on `.mx-wall` (the phone `Drawer`, opaque) and on the folded list
  `.mx-list.mx-list-peek` (list tint over the fixed wallpaper: opaque, same look as the list kept beside the page);
  fills raised (cards 62/56 %, message box 86 %, `.mx-glass` 86 % with the cards' sheen + gradient rim); the
  `.mx-lg-pill` halo is neutral; the message box in focus lights its rim instead of `border-ring` + ring; the glass
  `box-shadow` replaced the ring of `.mx-lg-btn` / `.mx-lg-pill`, so a soft `:focus-visible` outline instead.
- Web, gliding selection: `ActiveMark` now renders the active row's pill (`bg-accent` / `.mx-lg-pill`, `-z-10` in the
  `isolate` row) next to its bar and FLIPs both; `navRow(active)` no longer paints a background. `Segmented`: one
  absolute highlight placed from the chosen option's offsets (ResizeObserver: options may wrap), FLIP translate +
  scaleX on change; no animation with reduced motion.
- UI kit twins (rule a69): `ui-callout` fill = `--fill-1`, `ui-tile` = `--sunken` (hover `--accent`); Glass material
  = the app's liquid glass on `ui-card`, `ui-tile`, `ui-btn.ui-secondary/.ui-outline` (`html[data-material='glass']`:
  the app's `<html>` for page extensions; the widget frame's `<html>`, set by the bridge from `material` in the
  fragment and the `theme` message). `HtmlWidget` also sends `--fill-1`, `--sunken` and the `--lg-*` variables, and
  re-sends on a material change.
- Web, entrance order (top to bottom): boot `--bd` = height under the logo (index.html, no longer the radial
  distance) and also set on `.mx-rise` / `.mx-unfold` / `.mx-fade` (they played hidden under the loader before);
  session tree `--i` = running row index (`rowAt`, was `pi * 2 + ti + 1`: a project's 3rd topic rose with the next
  project); `SectionStack` cards after the section title; `.mx-card-in` sets `--cd` and its rows / fades / chart /
  end dot wait for it (the dot's `[animation-delay:720ms]` was overridden by `.mx-pop` and played at once).

## 2.0.0-alpha.149 - 2026-11-13

- Web, file viewer loaders: `features/files/skeletons.tsx` (`FileSkeleton({kind, preview})`: picture, PDF page,
  prose, table, numbered code lines, media, card; `CodeSkeleton` / `ProseSkeleton` / `MediaSkeleton` moved there
  from `viewers.tsx`), used by `Viewer.tsx` (probe and version pending), `FilePreview.tsx`, `pages/files/FileView.tsx`
  and `HtmlView`. `.mx-file-wait` (`globals.css`): fades in after 120 ms, one `::after` band sweeps by transform
  (`mx-sweep`); bones are `bg-muted-foreground/15` (visible in the dark theme).

## 2.0.0-alpha.148 - 2026-11-13

- Copies, review before integration: a pull request from a fork or from outside the repository (`fork` / `outside`)
  gets neither the clone's ignored files (`.env`, `.worktreeinclude`) nor its prepare command (`npm ci` runs the
  PR's scripts with the server's rights); a copy whose session could not be made (`_copy_env` error,
  `store.create` failure) is removed with its branch (`worktrees.undo`). `maxxing sessions new --file` checks the
  files before the session exists. `agents.voice_heard` compares real paths (workspace behind a link) and runs
  under the agents lock (a transcript faster than `_fire`'s post waits for it). Agents' `/` menu: "This
  conversation"; "Default" in an agent's model picker shows the agent's model (`defaultModel`). Tests:
  `test_worktrees.py::test_a_strangers_pull_request_runs_nothing_before_it_is_read`,
  `::test_a_copy_that_fails_halfway_leaves_no_folder_nor_branch`, `test_mentions.py`, `test_agent_voice.py`.
- `maxxing sessions new TOPIC [TEXT...]` (`cmd_sessions._new`): `<project>/<topic>` or a full path, an agent path
  refused (`agents run`); `service.check_hops` (split from `relay_message`) refuses before anything is created, then
  `create_session` (title = `titles.provisional` of the text unless `--title`, `auto_title`) and the first message goes
  through `relay_message` (from a turn: `relay` with sender and hops, source `session`; from a shell: `cli`). Not in
  `agent_guard.CLI_ALLOWED`: refused in a sandboxed agent. Template `CLAUDE.md` row of `maxxing sessions` updated:
  **upgrade note at the version** - replace the row starting with `` | `maxxing sessions send`` by the template's.
  Tests: `tests/test_mentions.py::test_sessions_new_…`.
- Agents' box like a session's. `POST /api/agents/{p}/{t}/{a}/run` takes `voice` (a file under the agent's
  `attachments/`, checked like the attachments) and `effort` (a new conversation's); `agents.fire(voice=, effort=)`
  (owner's words only) hands `voice_path` to `service.send_message` / `create_session` (an empty message: no "Run
  your routine."), the run message of the thread carries `voice: [path]`, and owner messages that wait keep both.
  `voicejobs._run` calls `agents.voice_heard(path, audio, job)` for an agent path: the run message whose `voice` has
  the recording gets the transcript as `text` (or `voice_error`). Web: `OwnerMessage` shows `VoiceNote` (exported from
  `Items.tsx`); the agent `Composer` passes `onVoiceMessage` (upload, then run; refused = the recording comes back
  attached), its `ModelPicker` has the effort and patches the conversation's session once there is one
  (`useSession(chat_session)`), and the "/" menu comes from `useSlashCommands` + the new `pages/sessions/useSlashMenu.tsx`
  (the menu of a box without "@"). Tests: `tests/test_agent_voice.py`.
- Failed turn as one card (`web/src/pages/sessions/Cut.tsx`). `normalize.py`: an `assistant` event written by
  Claude Code in place of an answer (raw event with `error`: `rate_limit`, `server_error`, `authentication_failed`…)
  carries `error`; the `note` of `mx_done` with a non-zero code (not stopped, not timed out) carries `failed: true`.
  `log.ts` folds them into `cut` on the turn's `result` item (or on the `note` item when the process died before any
  result): the refused answer is no longer an `assistant` item, so its user message counts as unanswered.
  `endingCut(items)` = the failed turn the thread ends on; only that card has Resume / the model picker
  (`CutContext`, set by `Column.tsx`), and the `session.error` banner above the composer is hidden then. A result
  that is not ok without either mark (a stopped turn) stays the plain result line. Texts: dictionary group `cut`
  (not in the first load). The mock writes failed turns like the server.
- `MediaPlayer.tsx` `seek()`: writes `last.current.t` at once (it was only set by `timeupdate`), and while a
  source switch or a reload is on its way (`resume.current` set, `duration` NaN on the element) it moves the time
  to resume instead of being dropped. Before, the stall of a seek made the player take the Auto copy and resume at
  the time before the seek.
- Separate copies (`maxxing/worktrees.py`, plan `code-worktree-pr`): session meta `worktree`, `runner._cwd` runs the turn
  in the copy and `_copy_note` adds a line to `--append-system-prompt`; `titles.refine` / `update_session` rename the
  branch (`worktrees.rename_for_title`) until it has an upstream; `move_session` refuses (`409 has_copy`); routes
  `/api/code/copy-repos`, `/api/code/copy-prefs`, `/api/sessions/{id}/copy{,/merge,/remove,/prepare-log}`,
  `/api/code/copies`, `/api/code/pr-session`; `<state>/worktrees.json` (per repository `prefix`, `prepare`,
  `copy_env`), `<state>/worktrees/<sid8>.log`. `search.SKIP_DIRS` and `backup.PRUNE_DIRS` skip `worktrees`.
- Pull requests: `gitview.github_pull`, `pull_comment`, `pull_review`, `pull_merge`, `pull_close`; `_gh_send` takes a
  method (PUT merge, PATCH close; 405/409 -> `409 refused`); `github_pulls(full, state)` adds `state`, `outside`,
  `review_me` (requested reviewer among the server's accounts); `codediff.parse_patch` shared by `codediff.diff` and
  the PR files. Routes `/api/git/pull`, `/api/git/pull/{comment,review,merge,close}`, `/api/git/pulls?state=`.
- Web: `features/code/{copyApi,prApi}.ts`, `NewCopy.tsx` (new session), `CopyBar.tsx` (bar + end window + header
  mark), `PrPane.tsx` (viewer paths `mx-pr:<owner/name>|<n>[|files|checks|file|<path>]`, one pane per PR), `DiffRows.tsx`
  (diff rows shared with `ChangesPane`), `PrReviewBlock.tsx` (` ```pr-review ` in `markdown.tsx`; PR text is rendered
  with plain code blocks). Git page: `PullList` (filters, opens the PR view, also on a clone of a GitHub repository),
  `CopyList`. i18n namespaces `copy`, `pr` in the `code` group. Tests `test_worktrees.py`, `test_pulls.py`
  (`_conn_helpers._Server` answers PATCH).
- Copies, round 2 (needs reported by T3 Code users): `.worktreeinclude` (`worktrees._copy_included`: `ls-files
  --others --ignored --exclude-from` then `check-ignore`, capped `INCLUDE_MAX` / `INCLUDE_BYTES`); a block of 10 ports
  per copy (`_free_ports`, meta `port`, `MAXXING_PORT` + `MAXXING_COPY_PATH` for turns - `runner` - and the
  preparation, `_copy_note` names them); `gitview.merged_pull` + `branch_status.merged_pr` (the last merged PR of a
  branch with no open one) and `copy/remove {merged_pr}` (looked up again server-side; branch deleted when its tip
  is in the PR's head, so squash merges count); `api/code._pr_text` appends the repository's pull request template
  (`PR_TEMPLATES`). `codediff.repo_head` reads `remote.origin.url` (no `insteadOf` rewrite, as `gitview` does).
- Workspace template: `CLAUDE.md` (separate copy, PR view) and the help index line `35-code.md`: carried over by the
  upgrade note of the next version.
- PR watch (`maxxing/prwatch.py`, loop in `api/code.py` startup, `MAXXING_PRWATCH_LOOP=0` in tests): `scan()` every
  `INTERVAL`; events `checks:<sha>` (all checks of the head completed, some in `FAILED`), `conflict:<sha>`
  (`mergeable` false / `dirty`), `c:` / `r:` / `l:<id>` (issue comments, reviews with a body or changes requested,
  line comments; OWN_ROLES only, never bots nor `_my_logins`); one `send_message(..., source="github")` per round,
  `MAX_WAKES` per `WAKE_WINDOW`, never while running; state `<state>/prwatch.json` (`seen`, `wakes`, `updated`,
  `done_sha`, `new` = first sight is history). Meta `worktree.watch` (`PUT /api/sessions/{id}/copy/watch`), `watch`
  in the copy status (false for a fork's / outsider's PR). Web: eye in `CopyBar`, source label `GitHub`.
- PR text by Claude: `POST /api/code/pr-text` (`_pr_draft`, `PR_PROMPT`, `_conversation` reads `mx_user` and `result`
  lines of the session log); `_ask_claude` shared with `_message`. The end window of a copy always opens for
  "Open a PR" (title + description fields, filled once, typed text wins); `codeApi.pr(repo, {title, body})`.
- Big diffs: `codediff.MAX_LINE_CHARS` cuts a very long line until "show all" (`cut`); PR files are parsed whole
  (`parse_patch(full=True)`, the PR view has no "show all"); a text file without GitHub patch is `too_big` (not
  `binary`), the PR view links to GitHub; `files_total` = `changed_files` when GitHub lists fewer.

## 2.0.0-alpha.147 - 2026-11-13

- Audit fixes (straight to `main`, merged here): `approvals.py` survives a WebFetch request whose URL does not
  parse; `sessions/opened.py` refuses an id with a final newline (`$` -> `\Z`); `cmd_agents.py` `show` reads the role
  file with `errors="replace"`, `set` catches `RecursionError` on a too deeply nested JSON value; `iconBtn`
  `pointer-coarse:size-10`; `MessagePopup` truncates a long chat name. Tests in `test_approvals.py`,
  `test_sessions.py`, `test_agents_cli.py`.
- Side questions: `aside.ask` no longer refuses a thread whose `fresh` flag is still set when the session is
  `running` (`fresh` is cleared only when a turn ends, so the whole first turn of a thread - new session, or the
  thread after a compaction - answered 409 `no_thread`). The fork is tried; if Claude has not written the thread yet
  (`RESUME_LOST` on a first turn) the answer is 409 `no_thread` "This session is only starting". Checked with the
  real CLI: `--resume <csid> --fork-session` finds a thread 2 s into its first turn. Test:
  `test_sessions.py::test_side_question_during_the_first_turn_of_a_thread`.
- Web, session shortcuts window (`ShortcutsHelp` in `pages/sessions/index.tsx`): rows `/` (slash menu), `@`
  (mentions), Mod+Shift+V (plain paste, `plainPaste` of `Composer.tsx`) and Ctrl+J only when `settings.code_mode`
  (the key is caught by `Column.tsx`, Ctrl on macOS too); i18n `kbd.*` (the rows of the window, group `composer`:
  out of the first load, which was over `test_web_first_load`'s budget).
- Security: `codediff.diff()` and `raw_diff()` pass `--no-textconv` (a `diff.<name>.textconv` from `.git/config`
  bound by `.git/info/attributes` ran with the server's rights: `GIT_ATTR_SOURCE` only covers the worktree's
  `.gitattributes`, `--no-ext-diff` only `diff.external`); test `test_a_diff_never_runs_the_repository_textconv`.
- Workspace template: `templates/workspace/CLAUDE.md` gets a paragraph under "Use what Harness already has" (the
  Code mode terminal, opened only by the user: a terminal opened through `POST /api/term` is not in the drawer, whose
  tabs are per browser in `mx-terminals`; Revert / Changes view) and Hermes, OpenClaw on the `maxxing import` line;
  the help topic index: line `04-sessions.md` (Tabs or Zones, intelligence, `/`, `@`), line `29-team.md`
  (`maxxing team send`). Templates are copied only when missing: the upgrade note of the next version must carry
  these three edits over (check: the paragraph is absent; do: insert it from the shipped template).
- Web, sidebar last line: Settings is an `iconBtn` like the three others (`Sidebar.tsx`, `lead` of `StatusBlock`:
  tooltip + `aria-label`, `data-tour` kept), `SidebarLook` centres the four (`justify-center gap-2`); folded bar unchanged.
- Web, Sessions, Tabs <-> Zones: `useModeMotion` (pages/sessions/tabMotion.ts, `MODE_MS` 340, 35 ms between
  sessions). The places "before" are read during the render that changes `tabs` (the tab chips `[data-tab]` of
  `sessions-bar` when leaving Tabs, the columns when leaving Zones: the commit has not moved anything yet), the
  animations start in a layout effect: to Zones each column slides from its chip's x and unrolls (`clip-path`
  inset from the top, opacity); to Tabs each chip rises from its column's x and the shown session slides from its
  column's centre. Web Animations, `fill: backwards` for the delays, nothing under `prefers-reduced-motion`,
  nothing on load. The page's `bar` ref moved above the hook.
- Sessions, wording only: "Add now" is "Add to plan" (`sessions.queue.inject`, `injectTip`, `sessions.msg.injected`
  = "added to the plan"; docs/user/04-sessions gains its paragraph). Route, signal and runner unchanged
  (POST /api/sessions/{id}/inject, SIGUSR2, `runner_caps`).
- Web, sidebar status line: `components/shell/mood.ts`. `pickMood(facts)` (pure) returns ONE sentence (`key`, `vars`,
  `when` = times formatted by the hook, `level` ok / note / warn / error / idle, `to`, `issues`), most pressing first:
  open health problems (one sentence per issue `code`, `ISSUE_MOOD`; several = their count; an unknown code keeps
  `health.issues`), quota at 100 %, CPU >= 85 %, RAM >= 90 %, quota forecast, quota >= 90 %, disk >= 80 %, feed unread
  > 10, sessions unread >= 5, agents attention, Team unread >= 5, then the calm ones (just restarted, sessions
  running, 5-hour quota that will hold, night, 30 days up, `shell.allGood`). `forecast(window, length, now)`: the
  usage so far as a straight line to `resets_at` (window start = reset - 5 h / 7 d); says nothing before 15 % of the
  window or under 20 % used. `useMood()` gathers the queries the shell already runs (Team / Agents only when their
  page is on) and `useStatusLine()` (HealthIndicator.tsx) maps it to the line: `note` = amber dot without the alert
  background, the line is a link to `to` unless `issues` (problems window); two lines (`line-clamp-2`, whole text in
  `title`), masked in presentation mode when it holds figures; no chevron any more. Texts: `mood.*`, a
  dictionary group of their own (`mood` in i18n/groups.ts, fetched by `useMood` once the shell shows: the core dictionary
  is at its first-load budget, test_web_first_load); "Checking…" while they download.
  `shell.claudePct` and `usePlanPct` removed (unused). Bench: one capture per case with `page.route` on
  /api/system/health, /api/usage, /api/feed, /api/workspace/tree.
- Sessions: `ViewSwitch` (computer: one button left of New session, after the layouts button which comes and goes with the
  mode; its icon = four square bars whose shape follows `data-kind`, moved by the transitions of `.mx-view-glyph` in
  globals.css, so nothing plays at page load; `currentColor`, the colour of the ghost icon buttons beside it) and `TabsToggle` (phone) in `pages/sessions/Tabs.tsx`; the store's `tabs` defaults to true and `merge` sets
  it false for a stored `mx-sessions` key without the field (a browser from before keeps its columns). The Sessions
  page has no `PageHeader` on a computer (`useDocumentTitle` called directly): one `sessions-bar` holds the tabs and
  the actions, measured by a ResizeObserver (`tight` = New session and Waiting without their label). Removed:
  `SubtitleWithBadges`, `WhereBadge`'s `generic`, keys `sessions.description`, `where.howTo`, `where.topicHelpAny`,
  `tabs.toggle/on/off`.
- Feedback: `POST /api/settings/feedback/check` (`feedback.check`: one read-only `claude -p`, tools Read/Grep/Glob,
  cwd `system/help` when it exists, default model, 90 s, one at a time; verdict `send | answer | self` with `answer`,
  `prompt`, `topic`; fail-open: anything unclear is `send`); `forced` on `POST /api/settings/feedback` appends
  `FORCED_NOTE` to the message (the cloud is unchanged); `FeedbackDialog` answer view, session created with
  `prompt` in `topic`; mock routes for feedback; `tests/fake_claude.py` knows `--allowedTools` / `--add-dir`.
- Import: `importer.py` `HINTS` / `PROMPT` rewritten for Hermes and OpenClaw, `_entries` strips every single folder
  above the export, `_plan` finds the skill folder by its `SKILL.md` (`skill_root`) and takes `memories/MEMORY.md` /
  `USER.md` as root memory, `_apply` keeps the generated heading over an imported CLAUDE.md without one;
  `cmd_import.py` prints `finish_prompt`.

## 2.0.0-alpha.146 - 2026-11-13

- Code changes (`maxxing/codediff.py`, `maxxing/gitsafe.py`, `api/code.py`, docs/dev/API.md#code): the runner photographs
  the session's repositories before / after each turn (throwaway index -> `commit-tree`, refs
  `refs/maxxing/<sid8>/<n>/{pre,post}`, never pushed; `Attempt.touched` = files of Edit / Write / MultiEdit /
  NotebookEdit), log entry `mx_changes` -> event `changes`; meta `code_turn`, `code_repos` (≤ 8, also in `Session`),
  `code_base`. `gitsafe.py` holds the stdlib-only git primitives shared with `gitview` (the runner stays stdlib-only).
  Reads with `SAFE_GIT`; commit / push keep the repository's hooks. `maintenance.run` prunes photos > 30 days or of
  deleted sessions. `gitview.open_pull` / `branch_status`. Revert = `POST /api/sessions/{id}/revert` (409 while running).
- Web: `features/code/` (`ChangesPane` inside `Viewer.tsx` through `mx-changes:` paths, `useRevert`), `ChangesChip` on
  the result line (`log.ts` hangs `changes` on the turn's result and marks the user message `changed`), `sid` in
  `ItemCtx`, `QUOTE_EVENT` to the column's composer; undo bar inside the viewer (a toast's button cannot be clicked
  under a modal dialog). i18n groups `code`, `term`; `toast.action` takes a duration. Showcase `code`.
- Terminal (`maxxing/terminal.py`, `api/term.py`): config `code_mode` (read-only in `/api/settings`; `POST
  /api/term/enable {password}` via `auth._check_current`, `/disable` closes all). Shell = `setsid -c $SHELL -l` on a pty,
  child of the server (ends with the service; no tmux), 256 KB replay buffer, 4 max, 30 min idle reaper (`startup`).
  WS `/api/term/{id}/ws`: cookie + same origin + one-time token (30 s); binary output, JSON `{i}` / `{r}`. Web:
  `features/terminal/` (xterm.js 6 + addon-fit, lazy), drawer in `Column.tsx` (Ctrl+J, `/terminal`, `SessionOptions`
  `onTerminal`), per-browser store `mx-terminals`, not for `agentRun` / paths under `agents/`.
- Doctor: `check_stale_units` / `stale_units()` (transient services other than turns running > 7 days).

## 2.0.0-alpha.145 - 2026-11-12

- Sidebar: the pinned extension pages leave the page list for `ExtFolder` (`Sidebar.tsx`), after the pages; unfolded
  state `ui.extFolderOpen` (persisted, default true); its rows have their own drag order (`useDragOrder(..., 'ext')` ->
  `PUT /api/extensions/pins`); folded bar: a `DropdownMenu` beside the icon. `nav.ts`: `orderEntries` / `NavEntry` /
  `useUnpinnedPages` removed, `orderPages(items, order)`, `useNavEntries()` -> `{ pages, pins, end }`; the pages'
  drag saves `sidebar_order` without `/x/...` (old entries are ignored). `/x` (`pages/ext/hub.tsx`) removed: the route
  redirects to `/settings/pages`, Ctrl K's Extensions entry too; Settings -> Pages loses its All pages button.
- Team: `TeamNavExtra` keeps only the unread count (the hover button that opened the bubble list is gone). The Team
  page's chat header gets **Open in a bubble** (`team.toBubble`, bubbles on, desktop): `useTeamUI.openChat(id)`
  (also clears `hidden`) then back one step in the history (or `/`). `team.bubblesHiddenDesc` updated.

## 2.0.0-alpha.144 - 2026-11-12

- Sessions: the column menu (`DropdownMenu` of `Column.tsx`) is replaced by `pages/sessions/SessionOptions.tsx`
  (`Dialog`, bottom sheet on touch), opened by the "..." and by the header's right click / long press:
  `useContextMenu` takes `onOpen` (called instead of the menu at the pointer). `ColumnHeader` loses `onPlan`,
  `onNotify`, `onHud`, `tgLinked`; `SessionMarks` shows plan / notify while on. Removed: move left / right, copy
  ID (and their i18n keys, with `plan.toggleOn/Off`, `sessions.notify.label/off/unavailable`,
  `sessions.grid.(un)stack`, `sessions.layout.menu`, `sessions.menu.detach`). The layout picker still gets the
  focus (`keepFocus` = `onCloseAutoFocus` prevented while `layoutPicker === col.key`).

## 2.0.0-alpha.143 - 2026-11-12

- Web, list pages (`components/shell/PageList.tsx`): `PageList`/`ListHead` `search` ({value, onChange, placeholder}:
  the 🔍 of the head filters the list; touch without `search` = the palette, `searchNow`), `actions` (buttons of the
  list in its head), `ListChips` (one-line filters), `ListEntry` (Overview / All rows). `Page` `sensitiveTitle`, its
  description is a `div`. Applied to Agents (`AgentsLayout/AgentsList/AgentsPage`, i18n "Office" -> "Overview", route
  `/agents/office` kept), Team (`TeamPage/Chat/Friends/Side`), Infra, Mail (`CountBadge exact` = no 99+ cap),
  Files (`HeaderSearch` and `useFileSearch` removed: Ctrl+K finds files), Tasks (`ProjectNav` `query`/`matched`,
  the list search = `TaskFilters.q`), Feed, Sessions (`SessionTree` `query`, also in `SessionsPanel`).
- Web, Git (`features/git/GitPage.tsx`): `GitNav` = the sources only (`?source=github`, `&account=<login>` with
  several accounts); `SourceCards` = the former cards; `RepoView` in its own `Page` (title, Server | GitHub
  `Segmented`), side column (commit, pull requests) from 1700 px, below it the commit opens in a sheet.
- Web, Infra: place colours unused (`PlaceTag`/`PlaceIcon` neutral, `MixBar` removed), one problems pill per list
  entry, `HowItWorks` in a `Dialog` from the header's ? (`extra` = the tab's note; `useHowItWorks` and its
  localStorage key removed), search = the list's, project `Select` + hidden toggle + refresh icon in the header.
- Web, touch: `TouchNav.tsx` one left drawer, level 1 = `<Sidebar drawer />`, level 2 = the page's list (`LISTS`,
  `levelHere`, `.mx-level-in/back` in globals.css); `TouchAppButton`/`TouchSearchField` removed.
- Web, sidebar: last line Settings + `SidebarLook` (theme, presentation) + Help (`iconBtn` in `nav.ts`); health line
  -> `/feed` or `IssuesDialog` (one card per open issue, `ISSUE_TO`); `StatusPanel`, `HealthMeters`,
  `HealthIssues` removed.
- i18n: new group `composer` (`slash`, `mention`, `effort`; keys were `sessions.slash.*`, `sessions.mention.*`,
  `sessions.effort.*`), loaded on the first key asked: keeps the first-load dictionary under its budget.
- Sessions, safety of `sessions send` / `@`: `service.find_session` and `mentions.resolve` refuse an agent's sessions
  (`403 agent_session`; `agents send` only); `mentions._plain` (Team names: one line, no `[]` or backticks, 64
  chars); `service._merged_relay`: one sender = its relay kept, mixed = a preface per relayed text and `relay =
  {hops: max}`; `runner._inject_step` raises `turn_hops` to the injected item's hops. Tests `test_mentions.py`.
- `tests/test_web_ext_hub.py`: the touch drawer's entry comes from `<Sidebar drawer />`.
- Sessions: meta `effort` (`spawn.EFFORTS` = low|medium|high|xhigh|max, `""` = Claude Code's default) -> runner adds
  `--effort <level>`; `POST /api/sessions` and `PATCH /api/sessions/{id}` take `effort` (`400 bad_effort`), Session
  carries `effort`; a hand-off copies it. Agents and crons unchanged (no effort). `tests/fake_claude.py` knows
  `--effort`. Web: `ModelPicker` `effort`/`onEffort` (the `EffortRow` under the models, a 6-way segmented control),
  `PatchSessionBody.effort` is an instant field.
- Composer `/` menu: `pages/sessions/SlashMenu.tsx` (`slashItems`, `slashAction`, `SlashMenu`) + `slashCommands.ts`
  (`useSlashCommands(path, actions)`: session commands `model|effort|plan|compact|handoff|new|rename`, then the
  topic's skills from `GET /api/skills?path=` = `skills.for_topic()`). Composer prop `commands`: a session command
  typed in full runs instead of being sent (only without attachments or quotes); a skill is sent as typed (Claude Code
  expands `/name args` in `-p` mode, checked with 2.1.285). New-session form: `model|effort|plan` only.
  Menu groups (`SlashGroup` session | here | other, `SlashCommand.group`): skills ranked topic, project, others,
  `maxxing-*` last; with nothing typed a skills group over 6 rows shows 5 + a "+ N more" row (`SlashItem.expand`,
  Composer `expanded`); typing: names starting with it, then names containing it, descriptions only when no name
  matches.
- Composer `@` mentions: `pages/sessions/mentions.tsx` (`mentionAt(text, caret)`, `mentionRows` - grouped `@session` /
  `@agent` / `@team` with a title, folded like the `/` groups -, `usedMentions`), the
  same list component as `/` (`SlashMenu` now takes `MenuRow[]`, `label`, `keys`, rows with an `icon`); Composer prop
  `mentionsFor` (session id), `onSend(..., mentions)`. `GET /api/sessions/{id}/mentions` = `mentions.candidates()`
  (sessions not archived and not an agent's, running first, 60 max; agents if `agents_page`; `team.recipients()` if
  `team_page`). `POST .../messages` takes `mentions: [{kind, ref}]`: `mentions.resolve()` keeps known ones only (not
  the session itself, 8 max) with the label and command computed server-side, stored on the queue item (`_merged`
  keeps them); `runner.build_prompt` appends `mentions_note()` to the prompt (not to the logged/displayed text).
  `maxxing sessions send TO TEXT... [--file] [--json]` / `sessions list` (`cmd_sessions.py`):
  `service.relay_message()` + `find_session()` (id, 6+ char prefix, folded title exact then unique prefix, archived
  last); item `relay: {hops, from, title, path}`, source `session` (from a turn) or `cli`; `build_prompt` prefixes
  `relay_preface()`; the `mx_user` line carries `from: {session, title}` (normalize -> user event `from`, shown as a
  link). Loop guard: the runner writes `turn_hops` (the item's hops) in the meta; `agent_guard.agent_turn()` depth =
  max(agent depth, turn_hops), so sessions and agents share one count: `sessions send` refuses hops > `MAX_HOPS` (3,
  429 `too_many_hops`), `agents send` keeps `agents.MAX_DEPTH`. Not in `CLI_ALLOWED`: refused in a sandboxed turn.
  Workspace template `CLAUDE.md`: a `maxxing sessions send` row (**upgrade note: add it to existing workspaces**).
  Tests: `test_mentions.py`.
- Team: `maxxing team send TO TEXT... [--file P] [--json]` / `team list` (`cmd_team.py`). `team.recipients()`
  (contacts -> dm, groups not left), `team.find_recipient(to)` (folded name `_fold`: NFKD without accents +
  casefold, exact name / person id / chat id / address / netloc / hostname, else a unique prefix; 404 lists the
  names, 409 the ambiguous ones), `team.send_to(to, text, files)` (409 `team_off` when `team_page` is off; dm created
  by `create_chat`; files copied into `files_dir()` by `_attach`, removed if the send fails, then plain `send()`).
  Not in `agent_guard.CLI_ALLOWED`: refused in a sandboxed turn. Nothing reads chats (design rule of team.py kept).
  The command writes team.json / peers.json from its own process: `team._lock` and `teampeer._lock` are now
  `config.ProcessLock("team")` / `ProcessLock("team-peer")` (were thread RLocks; order team -> team-peer unchanged),
  the server's outbox worker delivers the queued event within 5 s (`_wake` is per process) and calls
  `team.notice_outside_writes()` each pass: team.json changed by another process (signature != `_written`, set by
  `_save`) -> `bus.invalidate("team")`. Workspace template `CLAUDE.md`: a `maxxing team` row in the CLI table
  (**the version's upgrade note must add it to existing workspaces**). Tests: `test_team.py::test_cli_send_*`,
  `test_a_write_from_another_process_refreshes_the_pages`.

- Agents: `agent_templates.fields()` sets `sandbox: True` for every template that reads outside text: a webhook, a
  mailbox (as before) or a web tool pre-allowed in `allowed_tools` (`reads_web()`: `Bash(curl…)`, `WebFetch`,
  `WebSearch`), i.e. `sales`, `orders`, `watch`, `writer`, `uptime` too. Without it `Bash(curl:*)` ran unsandboxed
  with `approvals: False` and the template's `domains` had no effect (`agent_guard.settings()` uses them only in the
  sandbox). `--no-sandbox` / `sandbox: false` in the request still wins; existing agents are not migrated. Test:
  `test_agent_guard.py::test_templates_that_read_the_web_are_protected`.
- Dependencies: `server/uv.lock` certifi 2026.7.22 -> 2026.10.23 (GHSA-6q48-6c7w-9gw2), filelock 4.1.0 -> 4.2.10
  (`voice` extra, via huggingface-hub); `templates/remotion`: `overrides.zod` 4.6.7 (GHSA-mrhx-c7xc-m3w5; Remotion
  4.0.534 pins 4.5.4 exactly, 4.0.543 pins 4.6.7: drop the override at the next Remotion bump). The lock change makes
  `deps._up_remotion` reinstall the shared Remotion. `THIRD_PARTY_NOTICES.md`: these two lines only (the file has
  other drift on the JavaScript side, not regenerated here).
- Voice: `web/src/features/voice/mic.ts` holds the microphone of the device (`localStorage` `mx-voice-mic`, never
  sent to the server). `openMic()` (used by `useRecorder`, so by the mic button and the record test) asks for
  `deviceId: {exact}` and, on `OverconstrainedError` / `NotFoundError`, for the default microphone, keeping the
  choice. `useMics()` lists the `audioinput` devices (without Chrome's `default` / `communications` aliases),
  reloads on `devicechange` and on a change of the `microphone` permission; browsers give no names before the
  microphone is allowed: `named` is false and the row shows a button that asks for it (`MicRow` in `VoiceSetup.tsx`).
- Sessions: the answer to `POST /api/sessions/{id}/messages` carries the Session read right after the message was
  queued (`sent_items` lists it: state running, no pid yet). When it reached the page after the stream's `state`
  frame of the runner taking the message, it replaced the fresher Session, and no other frame came until the turn
  ended (the meta file is not written in between): the thread showed the message a second time as "Sending…".
  `useSendMessage` keeps the cached Session when its `updated` is later than the answer's, and the thread drops a
  `sent_items` entry whose `client_ids` are already on a user event of the log (`sentLeft` in `Thread.tsx`). The
  mock puts `client_ids` on the user event of a send, as the server does.

## 2.0.0-alpha.142 - 2026-11-12

- `agent_cost.saved_by_claude(done)`: `thread_cost.estimated` is set only when the lost turn ended with Claude
  Code's own exit after the runner's SIGTERM (`mx_done.code` 143, `SAVED_CODES`): after a SIGKILL (no exit within
  5 s, OOM) or a crash Claude saved nothing in its thread, and taking the estimate off the next turn counted it 0 $.
- `agents.on_turn_end`: `charge_unbilled(sid, at)` gets no `at` for a turn that died unrecorded (`turn_died`: its
  message has no `last_turn.at`, which still names the turn before).
- `stable` merged into `beta` with `-s ours`: the slow-connection fix pushed to `stable` (`f9af80a28`) is the same
  code as `d9efa0d09`, already in `beta`; `stable` is again an ancestor of `main` for `publish.py`.
- fake_claude: `HALFTURN HALFCOST=x` saves `x` in the thread and exits 143, like the real CLI on SIGTERM.

## 2.0.0-alpha.141 - 2026-11-12

- Cost of a lost agent turn, two fixes on top of `agent_cost`: (1) Claude Code still saves the cost of a turn
  stopped by SIGTERM in its thread, so the next `--resume` reports it again in `total_cost_usd` (measured: a killed
  turn was counted by the estimate, then again in the next turn's increase). `charge_unbilled` now adds its estimate
  to `meta.thread_cost.estimated` (same `csid`), and `store.turn_cost(total, prev, estimated)` takes it off the next
  reported increase, never below 0 (runner `Attempt.prev_est`, `aside.py`); `_record` writes a new `thread_cost`
  without it. (2) `last_turn(lines, at)` / `charge_unbilled(sid, at)` find the lost turn by its message's time
  (`last_turn.at`, from `agents._which_turn`): a queued message the runner already started no longer hides it.
- `test_skills::test_folders_with_a_name_that_is_not_utf8_are_left_out` uses its own `claude_dir` (it listed the user
  skills of the machine running the tests).
- `test_approvals::test_outside_events_always_ask_unless_trusted` was flaky: its user run read the outside run's result
  in its context as soon as `on_turn_end` had written it (then asked first, as designed since `020694531`); the user
  run now comes first.
- Upgrade note: agents whose cron jobs have a timeout above `limits.timeout_s` (now capped by `run_timeout`).

- #75 (20 reported bugs, 18 fixed, each with its test): `telegram/format.py` measures the 4096 limit in UTF-16 units
  (`_u16`, in `render`, `_split_big`, `code`, `plain`); `mail/send._text` (HTML fallback shared by draft, reply,
  forward); `mail/imap._size` counts a `=\r\n` soft break as 0; `infra/actions.pg_install` raises `start_failed` when
  `systemctl enable --now` fails; `infra/providers._fqdn` whole labels only; `infra/probe.parse_nginx` skips regex
  locations without `proxy_pass`; `mcp_auto.candidates` drops a user server hidden by a folder server of the same
  name; `teampeer.normalize` keeps IPv6 brackets; `api/settings` and `gitview.resolve` turn the `RuntimeError` of an
  unknown `~user` into 400; `api/dashboard._defs` ignores a layout of the wrong shape; `uploads._num` catches
  `OverflowError`; `shopify._local_time`; `cmd_video.pdf` catches `TimeoutExpired`; `cmd_agents` on/off/silent/loud
  catch `AgentError` (exit 2) and a role-only `--mail` sets `allowed_tools` to `Bash(maxxing mail:*)`;
  `importer._claude_config` no longer exempts `.md` under `.claude/agents|commands` (`EMPTY` message);
  `agent_guard.topic_edit_denied` always denies the topic's `.mcp.json` (the sandbox mount still skips a missing
  one). Not taken: autoconfig "plain" -> none (kept "ssl"), project description with a `## ` line.
- `office.useDesk` spreads `useAgentMenu` (the menu of the agents list) on the desk and returns its `menu`, rendered
  by the Space view's `Console`: the right click / long press works on the desks too.
- `backup.LEAKS` "password": a value that is a whole upper-case name with an underscore (a vault key name such
  as `P30J_CF_PASSWORD`) is not a secret; a value that only starts like one is still caught. Tests in
  `test_backup.py::test_scanner_ignores_names`.
- `crons.restore_job` goes through `_commit(old, jobs)` like `create_job`, `update_job` and `delete_job` (crontab,
  then `jobs.json`, the crontab put back when the save fails). It called `sync_crontab` then `_save_raw`, so a failed
  save left a crontab line for a job that `jobs.json` does not hold. Test added in `tests/test_crons.py`.
- `tests/test_search.py::test_unchanged_sessions_are_not_read_again` counts only the `store.read` calls of its own
  thread: the sessions watcher of the test server (`service._scan`) reads the same metas in the background, and the
  test failed now and then when its pass landed between `reads.clear()` and the assertion (with the next fix: 3 runs
  of `test_search.py` out of 12 failed on beta, 0 out of 20 with both).
- `api/search.startup`: `MAXXING_SEARCH_LOOP=0` leaves the background refresh loop off, like `MAXXING_CRON_TICK=0`;
  `tests/conftest.py` sets it. The loop started with every test server and could clean the index up before
  `test_search.py::test_data_files_leave_the_index_and_the_base_shrinks` did (its "compacted" log was then
  missing).
- `trash._item` refuses an id longer than 255 bytes (`400 bad_id`): `Path.exists()` raised `OSError` ENAMETOOLONG
  (Python 3.12 only swallows ENOENT, ENOTDIR, EBADF, ELOOP), a 500 on restore and delete. Test in
  `tests/test_trash.py`.
- `feed.mark_read` passes `source` through `_utf8` like `post()`: a lone surrogate (valid JSON) raised
  `UnicodeEncodeError` in SQLite, a 500 on `POST /api/feed/read`. Test in `tests/test_feed.py`.
- `gitview._is_repo` returns False on `OSError` ENAMETOOLONG (any other error still raises): a path component longer
  than 255 bytes made `exists()` raise it while `resolve()` walked up to the clone, a 500 on every `/api/git/*` route instead of
  `404 not_a_repo`. Test in `tests/test_gitview.py`.
- `docs/dev/API.md`: rows for `PUT /api/system/auto-update`, `PUT /api/extensions/pins`, `GET /api/files/preview` and
  `GET /api/files/archive`, which the code served without a row.
- `tests/test_api_contract.py`: every route of the app and of each router of `maxxing.api.ROUTERS` (this FastAPI
  does not flatten included routers into `app.routes`; websockets and routes outside the OpenAPI schema count too)
  must have its `| METHOD | /api/... |` row in API.md. It reads the notations of the table (`ANY`, `[/{id}]`, `<x>`,
  `a\|b` and `{a\|b}` listing the values of the last parameter, a parameter inside a word such as `install.{kind}`);
  a whole-word parameter otherwise needs a `{...}` in its row. `/api/stream` (Global bus section) and the JSON 404
  are not rows; `KNOWN_MISSING` holds the agents' `chat/new` (being reworked). The `/api/ext/{id}` row now says its
  `{path}` is optional (`forward_root`).
- `components/ui/dialog.tsx`, `sheet.tsx`: the close button's `sr-only` text is `t('common.close')` (was "Close" in
  every language). `tests/test_web_labels.py`.
- `pages/sessions/Column.tsx`: the column and row resize handles take `t('shell.resize')` / `t('shell.resizeRows')`
  (new key, "double-click: equal heights", as `resetRowSplit` sets 0.5) as their `aria-label` (was "Resize").
- `presentation.hidden` (core group): the `aria-label` of the presentation-mode masks (`Sensitive`, the file viewers'
  placeholders, `MaskedLines` of the sessions), "Hidden (presentation mode)" in English in 8 places before.
- `web/src/pwa/index.ts`: a worker that reaches `installed` while a page is open is asked its `VERSION`; when every
  hashed file of the page's `index.html` (entry script, styles, read at `initPWA`) is in its `mx-assets-<version>`
  precache, the page is that build already (navigations are network-first): `SKIP_WAITING` with `silentSwap`, no
  reload. Before, only a worker already waiting at `load` was swapped silently; one still installing (precache on a
  slow link) went through `announceUpdate` and reloaded the freshly loaded page. No answer in 3 s or a file missing:
  the usual `announceUpdate` (a tab left open on an older build reloads as before).
- Sessions: the stack drop zone of a column (dashed third) was a local state of `ColumnShell`, cleared only by its own
  `dragleave` / `drop`; a cancelled drag fires neither. It is now `dropStack` in the sessions store (`setDropStack`),
  cleared with `dropBeside` by `setDragging(null)` (grip `dragend`, document `dragend` / `drop`), and one session at
  most shows it.
- Web i18n: `networkError()` (lib/api.ts) builds the `ApiError(0, 'network')` with the `common.networkError` text (core,
  en + fr, English fallback while the core chunk is pending); `request`, `uploadFileWithProgress` (files.ts) and
  `uploadAttachment` (sessions.ts) throw it, so `errorMessage()` and every direct `.message` read are translated. Route
  `feed` and `settings/:section` declare the `team` group (their `team.*` keys were '' while it downloaded). Known
  undeclared pairs, exempted in the test: `sessions/*` with `tasks` (first-load dictionary budget) and with `agents`
  (agents feature, out of scope). Tests: `test_web_i18n_groups.py`.
- `cmd_core.do_init` checks `--timezone` (`ZoneInfo`) and `--public-url` (`config.PUBLIC_URL_RE`, now shared with
  `api/settings.py`) before any write, as `PUT /api/settings` does: the URL is stripped once and that value is stored
  (whitespace-only clears), `SystemExit` with a message, `config.json` untouched. A host without tz database now fails
  early on `init --timezone UTC` (`install.sh` installs tzdata). Tests: `test_cmd_core.py::test_init_refuses_an_unknown_zone_or_a_malformed_url`,
  `test_init_normalises_the_public_url_it_stores`.
- CLI output: `cmd_proxy` status hint f-string; `cmd_deps` (`deps check --json`) prints `{checked: 0, vulnerable: [], skipped}` when
  OSV is down; `cmd_import._fail` prints `{"error": code, "message"}` in --json; `cmd_mail list` clamps `--page` with `max(0, ...)`.
  Tests: `test_status_names_the_port_when_the_address_is_on_no_interface`, `test_check_json_stays_json_when_osv_is_unreachable`,
  `test_cli_json_errors_stay_json`, `test_cli_list_never_passes_a_negative_page`.
- CLI errors instead of tracebacks: `cmd_deps._unknown` (verify/update check names through `deps.get`, exit 1);
  `cmd_deps` update also refuses a name that is in the manifest but not in `deps.UPDATE_ORDER` (caddy);
  `crons.spawn_run` wraps `OSError` of Popen and `systemd-run` in `CronError("spawn_failed")` so `cmd_cron` falls back
  to running the job inline, and a `systemd-run` timeout in `CronError("spawn_timeout")` (the unit may still start:
  exit 1, no inline run, the tick's catch-up recovers the slot; `api/crons._bad` maps both to 502); `cmd_cron._stamp` shows `????-??-?? ??:??` for a bad run time
  (list: last run, retry, and the removed-jobs list now also tolerates a missing `at`) and `run --if-due` answers exit 2 on a `CronError` of the schedule; `cmd_video.pdf` ends
  in `SystemExit("PDF failed: ...")` when the output folder cannot be created; `cmd_voice` prints errors to stderr
  and catches a failed `download_model`. Tests: `test_deps.py::test_verify_and_update_refuse_an_unknown_component`,
  `test_pdf_into_an_uncreatable_folder_raises_system_exit`, `test_cli_voice_download_prints_failures_to_stderr`;
  `test_crons.py::test_cron_run_detach_runs_here_when_systemd_run_cannot_be_executed`,
  `test_cron_run_detach_does_not_run_twice_when_systemd_run_times_out`,
  `test_cron_run_if_due_with_a_broken_schedule_is_an_error`, `test_cron_list_survives_a_bad_time_in_the_run_history`.
- DESIGN.md §8/§11: the 9 `window.confirm` of Mail (`Compose`, `MailPage`) and Team (`Chat`, `Friends`) use
  `confirm()` of `ui/alert-dialog` (Compose's `useBlocker` effect proceeds/resets from the promise; `run`, `tryClose`,
  `remove` are async); `pages/sessions/Tabs` arrows lose `backdrop-blur`. Test: `tests/test_web_design_rules.py`
  (browser dialogs and backdrop blur in `web/src`; only `features/agents/OfficeFuture.tsx` is exempt from the blur).
- Hand-edited state of the wrong type falls back to the default: `api/settings.current` (`result_line_hidden` must be a
  list), `extensions._ext_list` (`extensions.disabled` / `pinned` must be lists, used by `disabled_ids`, `pinned_ids`,
  `_pinned_list`), `config._path_setting` (`workspace`, `files_root`, `claude_dir` must be non-empty strings),
  `backup.history` skips history lines that are valid JSON but not objects, `gitview._root` uses
  `config.files_root()`. Tests:
  `test_a_hand_edited_result_line_hidden_of_the_wrong_type_never_breaks_the_settings`,
  `test_hand_edited_extension_lists_of_the_wrong_type_fall_back_to_empty`,
  `test_hand_edited_path_settings_of_the_wrong_type_use_the_defaults`,
  `test_hand_edited_history_lines_that_are_not_objects_are_skipped`.
  Not covered: the other raw readers of these settings (`sessions/runner.py`, `cmd_core.py`, `cmd_mcp.py`,
  `spawn.py`, `api/settings.py` returning the raw value).
- `workspace.update_project` / `update_topic` run the validation (slug, emoji, permission mode, allowed tools) and the
  busy (`409 has_running_sessions`) and destination (`409 exists`) checks before any write; they used to save emoji /
  `permission_mode` / `allowed_tools` first, then refuse the rename. Tests: `tests/test_workspace.py`
  (`test_a_refused_topic_rename_saves_nothing_else`, `..._of_a_busy_topic_...`, `test_a_refused_project_rename_...`).
- A lone surrogate (valid JSON, not encodable to the UTF-8 state files) is refused where it is validated instead of
  raising `UnicodeEncodeError` in `config._atomic_write` (500): `api/dashboard.layout` drops such ids (reuses
  `api.settings._utf8`), `workspace.check_emoji` -> 400 `bad_emoji`, `backup.clean_include` -> 400 `invalid_include`
  (reuses `backup._utf8`), `api/settings` `public_url` -> 400 `invalid_url` (`_utf8`; other non-ASCII still accepted).
  Tests: `test_dashboard`, `test_workspace`, `test_backup`, `test_settings`.
- `api/files.resolve` refuses a NUL in the last name with 400 `bad_path` for `follow=False` and `new=True`, which never
  resolve the last part (mkdir/move raised `ValueError`, 500). `follow=False` on an existing path (`/delete`, the `from`
  of `/move`) with a NUL in the last name now answers 400 `bad_path` instead of 404. Test: `test_files_guard`.

## 2.0.0-alpha.140 - 2026-11-11

- `agents`: outside provenance follows a result into the next session. `on_turn_end` marks the `result` message
  `outside: true` when the session was started by outside text (`MAXXING_AGENT_OUTSIDE=1` without
  `MAXXING_AGENT_OUTSIDE_FROM=context`; in a group, `agent_rooms.turn_outside`). New `_context(path, own) -> (text,
  outside)` (`context()` unchanged for callers). A new conversation of the owner (`_owner_chat`) gets `own=True`: the
  marked results are left out of its context, since outside text never enters the owner's conversation (and
  `MAXXING_AGENT_OUTSIDE` would take the manager away from it). Any other start that gets the context (a script's
  `agents run`) and finds a marked result in it gets `MAXXING_AGENT_OUTSIDE=1` + `MAXXING_AGENT_OUTSIDE_FROM=context`,
  so `run_settings` forces approvals unless `trust_outside`; its own result is not marked, so the mark does not renew
  itself: it lasts while the marked result is among the last `CONTEXT_RESULTS` (3). Accepted limit: what that run
  repeats of the outside text is unmarked one run later. API.md: `AgentMessage.outside?`. Results written before
  this change carry no mark. Test:
  `test_agents.py::test_the_result_of_an_outside_run_keeps_its_provenance_in_the_next_sessions`.
- `nav.useUnpinnedPages()` (page extensions on, without error, not pinned): while > 0, `Sidebar` ends the page rows
  with `hubItem` (`/x`, `data-tour="nav-extensions"`, not draggable, not in `sidebar_order`) and `TouchNav` adds an
  Extensions tile. `tests/test_web_ext_hub.py` checks both.
- The `/x` hub (`pages/ext/hub.tsx`) had no link left since the sidebar shows only pinned pages: `CommandPalette`
  gets `nav:x` (keywords extensions, pages, plugins) and Settings -> Pages an **All pages** button (`ext.allPages`, unused
  until now); `docs/user/13-page-extensions.md` says where it is. `tests/test_web_ext_hub.py` checks both links.
- Tasks: the view switch leaves the header below 480 px (was 400: on 393-412 px phones it pushed the touch Menu
  button to x 398-442, 14 px of it on screen); feed **Show more** gets a `pointer-coarse:before` hit area (50x16 ->
  66x28, exactly the gap to the title and the actions above and below: it never takes their taps). `tests/test_web_mobile.py` checks both.
- `telegram.gateway.forget()` also deletes `new.json` (`_new_path()`, the messages waiting for the "where?" answer).
  It was left behind, so `_new_restore()` revived the pending question after the next link. Test added in
  `tests/test_telegram_reliability.py` (`test_forgetting_the_bot_drops_a_pending_where_question`).
- `skills._front`: the block scalar header (`|` or `>`, with the chomping sign `-` or `+`) is stripped by one regex;
  `|-` and `|+` left their sign at the start of the description ("- Line one"). Test added in `tests/test_skills.py`.
- `agents.clean`: `triggers` is read as a list only when it is one (the slice ran before the `isinstance` check, so a
  dict raised `KeyError` and an int `TypeError`); `_clean_avatar` looks a value up in `_OLD_AVATAR` only when it is a
  string (a list was unhashable). `GET /api/agents/<topic>/<agent>` failed with an error for such a file. Tests added
  in `tests/test_agents.py`.
- Radar fixes merged from `main` (one commit each, with its test): `claude_models` (a non-list `data` is a failed
  read; a preview/variant suffix is not a newer model), `agents.clean` (lone surrogate in a rule -> 400 `bad_rule`, a
  limit too big for a number -> 400), `infra.probe` (`bad_probe` marks only its server), sessions (a change of Plan
  mode, model or permissions restarts the process before the next message), web (composer cap kept while Send is
  tapped, Tasks `tight` below 480 px of page width, agent settings chip track `minmax(0,1fr)`, feed Show more hit area,
  folded sidebar compact rows under 820 px of height with an edge fade).
- PR #74 (review of 2.0.0a139, agents): owner messages queue instead of `busy`; Run now fires the routine; a Free agent
  that gets outside text turns Protected; an allowed safety change applies the values of its card; a sandboxed agent
  never writes `.maxxing.json`; a turn bigger than the 512 KB tail read keeps its answer; the thread refetches only on
  its own agent's turns and keeps its place across pages; silent agents answer on Telegram; settings show the
  conversation's model; French texts say vous. Tests: `test_agents_conv_fixes.py`, `test_agent_safety_changes.py`,
  `test_agent_turn_bus.py`.

## 2.0.0-alpha.139 - 2026-11-10

- Fixes before release: `agent_guard._manages` reads the target with `cmd_agents._configure`'s parser
  (`parse_known_args`; `--name writer other` targets `other`) and `cmd_agents._handler` refuses a manager command of
  `AGENT_OWNER_ONLY` on another agent; `silent` / `loud` joined `AGENT_OWNER_ONLY` (and `AGENT_MANAGER`);
  `check_cli` takes `-h` / `--help` as help only before `--`. `on_turn_end` finds the ended turn by
  `last_turn.at` (the runner writes the `mx_user` time there) and `turn_died` (watcher: error without a recorded
  turn): `service._ended_turn(evs, at, died)` -> `ended_turn_text` / `ended_turn_steps` never take another turn's
  answer, tools or model (no `at`: the old last-result rule). UI: `fetchAgentThreadBefore` (`?before=`, pages of
  200 when the flow is scrolled to its top, view kept in place); the composer's model is the agent's
  (`chat_model` or `model`) unless picked, and is sent only when picked; `NewAgentForm` explains an empty slug.
- `pages/ext/index.tsx`: `t` / `navigate` read through a ref, not effect deps (`useT()` changes with each
  dictionary group: ~10 remounts of an extension page while it opened).
- **Agent chat** (every agent, no switch: a `chat` key left in an agent.json is dropped by `clean()`):
  `limits.chat_idle_h` (6, 0-720). `agents._fire`: the owner's own words
  (`_owner_chat`: trigger manual/telegram, source manual/telegram, no outside `text`) go on in the session kept in
  `<state>/agents/<key>.json` `chat: {session, at}` (`_chat_session`: gone, failed, other path or idle > chat_idle_h
  -> new session, which gets `context()` as before). `new_chat()` + `POST /api/agents/{p}/{t}/{n}/chat/new` +
  Telegram `/new` in an agent thread (`agent_new_chat` text). Run posts carry `owner: true` (and `chat: "new"` when
  they open a conversation); `gate(owner=True)` skips runs_per_hour and `_runs_last_hour` leaves owner runs out; a
  `busy` owner message that goes on in the running session is let through (`_joins_running`: it queues under that
  run's hold). `status()` gives `chat_session`. `on_turn_end` reads `service.ended_turn_text()` (the answer of the
  last turn with a `result`, even when a queued turn already started) instead of `last_assistant_text(turn_only=not
  ok)`, which posted the previous turn's answer again in a continued session. UI: `AgentPage.tsx` live text/tool in
  `Working` (`useSessionLog`), `ChatLine` divider, New conversation bar, Reply hidden on the open conversation;
  Settings -> Limits switch + `chat_idle_h` field (`LimitsFields chat`).
- **Agent page = one flow** (`AgentPage.tsx` `AgentCenter` -> `Flow` + `Composer`, no tabs, no `SessionColumn`): the
  thread oldest first with day lines; owner runs = bubbles on the right (reply tag when `reply_to`); other runs =
  `TriggerCard` (icon by trigger); results = `AgentTurn` in `AgentBubble` (avatar): a turn of an own session
  (`ownSessions`: chat, last chat, sessions of owner runs without `reply_to`) shows its steps as rows (`StepList`) and
  a `ResultLine` (model, duration, cost), a run's result folds them (`StepsFold`) with Reply / Open the run / Continue;
  "Memory updated" when a step edited `memory.md`; `changed_chat` notes = a green `ChangeLine`; `new_chat` notes and
  a `chat: "new"` owner run after an earlier one = a "New conversation" line; each running session = `LiveTurn`
  (steps and text of its current turn from `useSessionLog`, Stop; Open the run for a run only) right under the last
  message of its session. A conversation turn has no link to a session view and is never folded (`FOLD_CHARS` only for
  runs); its answered approvals are one line (`approvals.tsx` `ApprovalLine`). The manager may run itself:
  `maxxing agents run <itself>` in a manager turn (`AGENT_MANAGER` += run) = `fire(trigger manual, source
  "conversation")`, a run of its own ("Started at your request, from the conversation"); `MANAGER_NOTE` tells it to
  do so when asked to do its routine now; the conversation hands its hold of the day's budget over to that run
  (`agents.hand_over`), else the run would find it all held (busy).
- **Conversation from the Office**: `AgentsOverview` keeps `?chat=<agent path>` and gives `office.tsx` `OfficeChat`
  ({open, current}) to the desks (`useDesk`, `AgentTile`): a desk toggles the panel instead of navigating (outside the
  Office the desk still opens the page). Panel = `AgentPage.tsx` `AgentChatPanel` (header + `AgentCenter`), docked
  440 px from 1024 px, else a `Sheet`. Extension views get `chat_route` per agent (`OfficeCustom`, the current
  pathname + `?chat=`).
- **Agents, simpler**: `agents.create()` defaults `sandbox` to whether the fields
  read outside text (`mail`, a `feed` trigger); `cmd_agents create` sets it for a webhook / mail template, `--sandbox`
  added; imports are free. `request_change` applies at once what only makes the agent safer (`_safer`,
  `_safer_limit`: sandbox on, approvals on, trust off, a stricter mode, subsets of domains / writable (any when the
  sandbox comes on) / keys / allowed tools, supersets of disallowed tools and rules, lower limits; mail and subagent
  always asked). `MANAGER_NEW` joins the manager's system note while its role (CLAUDE.md description) is empty.
  UI: `CreateAgent.tsx` = `NewAgentForm` (where + name + random character -> `POST /api/agents` with an empty
  description -> the agent page); the old 3-step form, `QuickCreate`, the gallery cards, `EditWithClaude` /
  `useCreateWithClaude` are gone (`draftUrl` stays for groups and custom Office views); the empty conversation of an
  agent without role shows the templates as `Suggestions` (`AgentComposerApi.fill`). `AgentSettings.tsx`: sections
  `essential | protection | mail | advanced` (`SectionId`; `?settings=mail` unchanged), `LimitsFields part`,
  `readsOutside()`; 46 unused texts dropped.
  Then: `MANAGER_NEW` sets the agent up in one turn from a brief (My job / When / Results / Never without me),
  freedoms decided by rule, questions only for what it cannot guess; `schedule_zone_note()` (config `timezone`) joins
  every manager note and `agents cron` prints the zone (the server clock may differ: `system_clock: keep`).
  `agent_templates.BRIEFS` / `brief()` / `FIRST_IDEAS` -> `brief`, `first` in `GET /api/agents/templates`;
  `Suggestions`: Blank brief + 6 ideas + "more", `fill()` selects the first `[…]`. Profile: one add-trigger menu
  (`agent-add-trigger`; Telegram row only when on), guards = budget + Free/Protected line (opens the Protection
  section) + approvals / keys when set; group link under Settings; `CronRow` shows `settings.timezone` when it is
  not the browser's. Skill `maxxing-agents`: same brief and rules.
- Removed the text as it is written (`--include-partial-messages`, `<sid>.live`, the SSE `partial` frame,
  `partialText`): not needed. The runner still drops `stream_event` lines. The manager's sandboxed turns pre-allow
  `agent_guard.MANAGER_SAFE` (Read, Glob, Grep, WebSearch; the deny rules still win).
- "New conversation" moved under the box; "Edit with Claude" only in the profile. Results now carry the
  turn's steps: `service.ended_turn_steps(sid)` -> `tools` ([{name, summary (160 chars), error?}], the last 40),
  `tools_total`, `model`, `duration_ms` (omitted when empty); older results have none. `RunView` goes back to the
  agent page (no `?tab`). The chat notes (change requests answered) go into the manager turn's system note
  (`run_settings`) instead of the owner's message, so a message typed in the session's own box gets them too.
  `BUS_TURN_KEYS` += agent one/thread (a run started by another process reaches the page by the session watcher).
  Settings: the `chat_model` picker is gone from the UI (field kept).
- **Agent manager (the owner's conversation)**: a new chat session gets `MAXXING_AGENT_CHAT=1` in its meta env and no
  model of its own; `agents.manager_turn(meta)` (chat, no outside, no group) -> `run_settings(manager=True)`: model
  `chat_model` (new agent.json field, "" = `model`) or `model`, `MANAGER_NOTE` instead of `OWNER_NOTE`, approvals on
  when sandboxed (else the agent's), `agent_guard.settings(manager=True)`: `allowUnsandboxedCommands: true`,
  `autoAllowBashIfSandboxed: true`, its `CLAUDE.md` out of denyWrite / `permissions.deny` (the `agents/*/CLAUDE.md`
  glob dropped), `allow` `Bash(maxxing:*)` + `Edit(/<write dirs>/**)`. `agent_guard.agent_turn()` gives `manager` and
  `session`; `check_cli` lets the manager run `agents show|set|cron|webhook|watch|on|off` on itself
  (`AGENT_MANAGER`, `_manages`); `set` joins `AGENT_OWNER_ONLY`. New CLI `maxxing agents set <agent> FIELD=VALUE|--json`
  (owner: `update()`; manager: `agents.request_change`) and `maxxing agents cron <agent> --job ID [--schedule]
  [--prompt] [--on|--off] [--remove]` (its own jobs only). `request_change`: validates the whole target with
  `clean(strict)`, applies the non-safety fields, writes an approval request `{kind: "agent_change", tool: "Agent
  settings", input: {description}, fields, expires: +7 d}` in `<state>/approvals/`; `approval_mcp.expire(session=)`
  and the watcher's orphan expiry skip that kind (it expires at `expires`), `prime()` announces it; `approvals.decide`
  -> `agents.change_decided` (applies on allow) and a `chat_notes` entry in the agent state, prepended to the next
  owner message ("Since your last message: ..."). `approvals.public` gives `kind`; `status().waiting` counts pending
  changes. `_fire`: a non-owner message never continues a manager session (reply_to -> new run). `on_turn_end`: a
  change by the manager is a `changed_chat` note. UI: `ApprovalCard` renders `agent_change` as one line per change,
  Settings -> Model "Model of the conversation" (`ModelSelect defaultLabel`), the self-locked line says the
  conversation can. Tests `test_agent_manager.py`.
- Runner: Claude Code's own permission questions on the control channel (`control_request` `can_use_tool`, e.g. the
  sandbox's `SandboxNetworkAccess {host}` for a host outside the domains) were never answered, so the command waited
  until its timeout. `_can_use_tool` answers them in a thread: through `approval_mcp.ask(ctx=...)` when the turn has
  approvals (an approval card), else a deny at once. `approvals.summary` reads `host`. `agent_guard.check_cli` never
  refuses `-h` / `--help`, and refuses any command run inside the sandbox (`in_the_sandbox()`: an agent turn's unit
  whose state is hidden; a command line with a pipe, `;`, `&&` is sandboxed as a whole and its writes would vanish).
  fake_claude: `ASKNET`. `public()` gives `chat_model`.

## 2.0.0-alpha.138 - 2026-11-10

- Released from `main` ("Urgent fixes" path). `server/maxxing/claude_models.py`: daily `GET /v1/models`
  (secrets token/API key, else the `claude login` access token while valid, `anthropic-beta: oauth-2025-04-20`),
  newest id per family -> `<state>/claude-models.json`; `service.KNOWN_MODELS` removed, `service.models()` uses
  `claude_models.latest()` (+ `forget_models_cache()`); config `default_model` follows its family when it was the
  previous newest (`_follow_default`). Started from `api/claude.startup` on the installed server only
  (`claude_update.installed_server()`, split out of `runs_here()`; `MAXXING_CLAUDE_MODELS=0|1`). `titles.MODEL`,
  `api.claude.TEST_MODEL` = `haiku`, `team.SUMMARY_MODEL` = `sonnet` (Claude Code family names). Telegram fallback
  list: Haiku 5.5 instead of 4.5. Tests `test_claude_models.py`.

## 2.0.0-alpha.137 - 2026-11-10

- Released from `main` ("Urgent fixes" path): the 45 Radar audit fixes validated by FEU and pushed straight to
  `main` on 2026-11-10 (Team peer endpoints and bubbles, trash/search with non-UTF-8 names, steering while only
  background tasks run, customized UI build swap, update-plan UI check, MCP login cap, DNS/mail checks, deps lock,
  log redaction, touch targets, responsive Tasks/Team/sidebar previews). One commit per finding, each with its test.

## 2.0.0-alpha.136 - 2026-11-10

- Released from `main` ("Urgent fixes" path). Phone keyboard and the session composer (issue #54, idea of PR #55):
  `styles/globals.css` caps the focused composer textarea (`data-kbd-cap`, `Composer.tsx`) to 30 % of `--vvh` with
  `overflow-y: auto !important` (the autosize sets it inline), and in the column being typed in
  (`html[data-kbd] [data-col]:has([data-kbd-cap]:focus)`) hides the place row (`data-kbd-hide`) and, under
  `max-height: 480px`, the header (`data-kbd-short-hide`, `Column.tsx`). Test `test_web_mobile.py`, DESIGN.md, doc 04.

## 2.0.0-alpha.135 - 2026-11-09

- Agent preview card (`features/agents/AgentHover.tsx` + `AgentPreview.tsx`, FEU's `ff43b2c76`): gated by
  `stores/ui.ts` `agentPreview` (per browser, default `false`, no persist migration: a missing key takes the default),
  switch indented under `/agents` in Settings -> Features (`features.agentPreview*`, settings i18n group). The room
  (`OfficeRoom`) is drawn only when `mx-agents-office-view` is `future` (or the old `game`), read once per card;
  otherwise a narrower card (300 px) without it. Doc 30.

## 2.0.0-alpha.134 - 2026-11-09

- First release of `beta` since a133 went out from `main`: carries a129, a130 and a132 (beta-only until now) to
  `stable`. `upgrade_notes(old, new)` keeps `old < v <= new`, so a stable install at a133 would skip their notes:
  `docs/upgrade/2.0.0a134.md` points to them. `changelog_since` is a git diff, so their CHANGELOG sections show.
- FEU's work on `beta` after a132 (no entry until now): Team bubbles (`features/team/TeamBubbles.tsx`,
  `stores/ui.ts` `teamBubbles` per browser, doc 29), sidebar boot loader + status footer meters, sessions tabs
  animation, emoji picker search (English names, accents folded; emoji data sent Brotli/gzip), palette settings
  keywords in French (`skw.*`), profile photo fixes (per-upload temp file, serialized removal, bounded failed
  fetch memory, Team photos pruned and pushed to group members), customized UI build kept while sources change,
  build never raises, ui-page centred in the extension kit.
- Second-level sidebar: `components/shell/PageList.tsx` = `SecondBar` slot rendered by `Sidebar.tsx` + `PageList`
  portal from each page (container = shell, content = page); `useClosedList` / `entryPeek` = hover peek of the
  current page's entry while closed, native events (the portal breaks React's synthetic hover). Shared width handle
  `components/shell/ResizeEdge.tsx`. `stores/ui.ts`: `secondBarOpen` (one for every page), `secondBarWidth`
  (`SECOND_W` 220-520, default 288), `sidebarCollapsed` defaults to false. Removed: `SessionsRail.tsx`,
  `AgentsRail.tsx`, `TeamRail.tsx`, `pages/sessions/RailTree.tsx`, `sidePanel.ts` (a133 rails; the hover previews of
  sessions / chats go with them). Users: Sessions tree, Agents list, Team chats, Tasks `ProjectNav`,
  Infra `InfraNav`, Files `Listing`, mail `FolderList` + `MailboxNav` (the old `FolderPane` is gone); mail shows two
  panes (list | message) from 760 px.
- Palette chips (`CommandPalette.tsx`): `CHIPS` / `chipOf` = type from the command id prefix (`session:`, `run:` =
  a session of an agent, `agent:`, `group:`, `task:`, `file:` / `name:`, `memory:`, `settings:`, `doc:`,
  `nav:`/`act:`/`help:`); page sources and providers have none (All only). A chip with `kinds` re-queries
  `/api/search?kinds=…&limit=60` (All: limit 36, 6 lines per async group + a "See the N" item). Counts = cmdk's
  own filter over the static commands + the All search's hits. Touch sessions drawer: `ListHead` (shared head of
  `PageList`).
- `NotificationsBell` removed: unread count on Home (`HomeNavExtra`, a dot when folded; Home tile of the ⊞ menu,
  Notifications tile removed); folded sidebar: search icon (palette) instead. Dashboard header bell unchanged.
- Agents: `features/agents/AgentsPage.tsx` `NewButtons` (New group outline + New agent primary, in the Office
  header; `?topic=` starts the group in its project); list without search / + / New group.
  Sessions: `Tree.tsx` `ListHeader` without filter (touch: New session right of the chips).
- Team: `features/team/TeamBubbles.tsx` `Tools` `chatId` -> close the bubble + `/team?chat=<id>`; the bubbles
  switch = `teamOptions` in `pages/settings/sections/Features.tsx` (sub-row of Team, per browser).
- Tasks: `features/tasks/Toolbar.tsx` `FilterMenu` (popover) + `FilterChips`, `FilterBar` and the search field
  removed (a `q` still in the URL shows as a clearable chip); New task = popover with the quick-add field, key `N`.
- Touch layout: `components/shell/TouchNav.tsx` `TouchListButton` (☰ = the page's `PageList` in the left drawer via
  `ListSlot`; Sessions keeps its own drawer; no button when the page registers no list), `openPageList()` (empty
  states), `keepPageListOpen()` (a click in the list closes the drawer unless the handler calls it: Files folders,
  mail mailboxes); edge swipe opens the same list in the installed app. Removed on touch: Tasks / Infra chip rows
  (`ProjectNav` column only), mail folders sheet + mailbox picker, `/agents` list page (phone = Office), Team list
  page (first chat; empty state button). `tour.nav.bodyMobile` updated.
- Mail: list width handle (`ResizeEdge`) in `features/mail/MailPage.tsx`, localStorage `mx.mail.listWidth`, min 280 px,
  360 px left for the message, double-click = default.
- Notifications `/feed` (`pages/feed/index.tsx`): `PageList` of sources (All + unread, To handle when pending, each
  source with icon + unread or total), day groups, `FeedItem roomy` (round level icon, 3-line clamp + Show more),
  header All / Unread + Mark all read (scoped to the source) + settings; state in `?source=`, `?pending=1`,
  `?unread=1`. `PageList entry` prop: the hover peek of a closed second bar binds to another sidebar entry (Home).

## 2.0.0-alpha.133 - 2026-11-09

- Released from `main` ("Urgent fixes" path; a132 is Romain's on `beta`). Permission mode `ask` (approval MCP for
  sessions, `allowed_tools` in `.maxxing.json`), runner in stream-json input (`on_steer` = control_request
  interrupt + injected message, fallback = kill; `MAXXING_STREAM_INPUT=0`), agent chat parity (`within` param on
  files raw/preview/thumb/stat, `/media-roots`), Feedback `image` ({mime, data base64 <= 1 MB, width, height},
  `feedback.image()`, bodylimit 2 MB on POST /api/settings/feedback; cloud: `lead_images`, 100 a day, 6 months),
  plus the Radar commits since a131.

## 2.0.0-alpha.132 - 2026-11-08

- Settings: `web/src/pages/settings/sections.ts` = 6 groups; new sections `appearance`, `skills`, `widgets`, `pages`,
  `templates`, `import`, `updates`; `support` removed (donations card in `about`). Redirects: `stats` -> `usage`,
  `license` / `support` -> `about`, `docs`, `packs` / `projects` -> `templates`, `extensions` -> `widgets`. Features =
  one `FeaturePages` list in sidebar order (`core` rows always on, `sub` rows for the session options).
  `CommunityLink` at the bottom of Widgets, Pages, Skills (no in-app library).
- Skills: `maxxing/skills.py` + `GET /api/skills` (read only, 6 KB of front matter per `SKILL.md`, origins product /
  user / workspace / project / topic).
- Profile photo: `maxxing/profile_photo.py`, `<state>/profile/photo` (JPEG / PNG / WebP by magic bytes, <= 512 KB,
  cropped to 256 px by the browser), `profile.photo` = first 16 hex of its SHA-256; `/api/settings/profile/photo`
  (GET / PUT / DELETE). Team: the profile sent to peers carries `photo`; a contact's photo = signed GET
  `/api/team-peer/photo` (contact or shared group key, pending requests refused), cached in
  `<state>/team/photos/<pid>-<version>` behind `/api/team/people/{id}/photo`; one deadline for the whole download
  (`teampeer.PHOTO_DEADLINE`), one fetch at a time per photo, hash checked. Older servers ignore the field. Emoji
  picker `frimousse`, data `emojibase-data` 16.0.3 copied into `dist/emojibase/{en,fr}/` by the vite plugin
  `emojiData` (no CDN).
- `maxxing init`: `agents_page` and `usage_widget` written once (true on a new install, false on an existing one).
  `maxxing status`: `Pages` line (`cmd_core.OPTIONAL_PAGES`, `pages` in `--json`).
- Customizable UI: `maxxing/webbuild.py` builds `web/src` into `<state>/web-dist` (`npm ci` once per lockfile with a
  reduced env, `tsc -b --force`, `vite build --outDir`), stamp `.maxxing-build.json` (`source_key`, never served:
  `spa()` refuses dot files); served only when the stamp matches the sources on disk (`cached_dist` /
  `active_dist`), else the shipped `web/dist`; `web-dist.prev` for rollbacks. `customs.save` refuses only
  `web/dist`; `customs.web_leftovers()`. `maxxing custom build [--force] [--json]`; `maxxing custom` shows the UI
  state and "Old UI edits". `maxxing update` stashes only `web/dist`, rebuilds after replaying customizations
  (`_rebuild_web_ui`; failure = warning, shipped UI, never a rollback). Preflight `ui_build` in the worktree (shares
  `node_modules` when the lockfile matches, never installs: `unchecked` otherwise; failure -> verdict `adapt`).
  Doctor check `web`. Skill `maxxing-customize` §1b.
- Templates: workspace `CLAUDE.md` (Customizing level 0, "Use what Harness already has", "Safety with shared code
  and data"), help / harness / tutorial topics, `extensions/README.md`, `extensions/pages/page.js` -> upgrade note.

## 2.0.0-alpha.131 - 2026-11-08

- Released from `main` ("Urgent fixes" path). `auto_compact_tokens` default 400000 -> 300000 (`config.py`; the
  Settings -> Claude "recommended" mark moves to 300k). Plus the Radar audit commits of 07-08/11 (one per finding).

## 2.0.0-alpha.130 - 2026-11-07

- Crons: `pages/crons` is the lazy section `crons` of Settings (data preloaded by `pageData.SETTINGS`); route
  `/crons/*` -> `CronsMoved` (`/settings/crons` + same search); server links (`crons._feed`, one-time missed event,
  widgets `crons` / `day`) point to `/settings/crons?job=`; tour step `crons` removed (the Settings step mentions
  them). Docs, skills and workspace / pack templates say "Settings -> Crons" (upgrade note for existing workspaces).
- Config `sidebar_order` (default `[]`, settings API, `RESTORABLE_CONFIG`): routes `^/[a-z0-9-]{0,40}$`, max 40,
  deduped; a broken saved value reads as cleaned (`api.settings.sidebar_order`). `nav.orderNav()` puts saved routes
  first and inserts any other page after its default predecessor; group `end` (Settings) always last. `useNav()`
  feeds the sidebar, the touch menu, the palette and the shortcuts.
- Pins: `extensions.pinned` keeps its order (`set_pinned` appends), `set_pin_order(order)` (only reorders existing
  pins), `PUT /api/extensions/pins {order}` (max 200), `info()["pin_order"]`.
- `components/shell/dragOrder.ts`: native HTML5 drag, one MIME scope per list (`nav`, `pins`), commit on drag end
  unless the drop was cancelled (`dropEffect === 'none'`).
- Sidebar: `navRow()` shared row style; Help menu removed; `StatusFooter` (`HealthIndicator.tsx`) = health popover
  (`HealthIssues`), meters link, `UsageLines` (`usePlanUsage`), icons (presentation, theme, docs, shortcuts when
  `any-pointer: fine`, General); the touch ⊞ menu renders the same footer (`touch`, `onInstall`). Donate links stay
  in Settings -> Support, What's new, Feedback and License (no longer in the sidebar / ⊞ menu).
- `ui/tooltip.tsx`: `KeepClass` - Radix `Slot` joined a function `className` (NavLink) into a string, so links in a
  tooltip (folded sidebar) lost their classes and active state.

## 2.0.0-alpha.129 - 2026-11-07

- Config `tasks_page` (default `False`, settings API, `RESTORABLE_CONFIG`). `maxxing init` writes it once when
  absent: `True` when the install state shows an older install (`version` / `initialized` / `default_crons`, same
  test as `health_feed`), `False` on a new one. A config without the key (code updated without `init`) reads as off.
- Off: the built-in widget `tasks` is not `available()`; `NavItem.setting` filters the `/tasks` entry out of
  `useNav()` (sidebar, tab bar, palette, `g t`) while it keeps its place in `NAV` (shown while settings load);
  the onboarding Done step shows a "Features" card instead of the Tasks one; the guided-tour step `tasks` is split
  into `tasks` (target `nav-tasks`, skipped when missing) and `crons`.
- Untouched: `/api/tasks`, `tasks.json`, workspace project sync, search indexing of tasks, the `/tasks` route
  (palette search hits still open it), the `maxxing-tasks` skill, the default job "Morning tasks" (created off).
- Workspace template: tutorial lesson 3 says where to switch Tasks on (upgrade note for existing workspaces).

## 2.0.0-alpha.128 - 2026-11-07

- Released from `main` ("Urgent fixes" path). Crons: catch-up of the last missed slot (24 h, not for jobs more
  frequent than hourly, not within 10 min of the next run, a killed run counts for its slot), retries (Claude:
  `classify_failure` on the turn's error and API-error-shaped answers, max 3, limit reset from the usage windows; shell:
  `retries` 0-5; only while the tick runs, stale retries > 1 h reported final, cleared on disable/enable), one-time
  jobs (`once_at`, `delete_after`, +5 years max), `[SILENT]` hint for notify "always" (`silent_ok`). Agent cron
  triggers skipped by their budget return a clean skipped turn. Web: `lib/touch-zoom.ts` (pinch in image/diagram
  viewers and text zoom; viewport zoom still locked elsewhere).

## 2.0.0-alpha.127 - 2026-11-07

- Security review of a126. Sandbox (`agent_guard.py`): `home_wall()` denies each entry of `$HOME` except the
  workspace, `HOME_BACK` (git config, `.local/bin`, package caches, tool folders) and `CLAUDE_BACK` (skills,
  shell-snapshots); shell rc files stay readable unless they match `SECRET_SET` (`SHELL_RC`). `SYSTEM_SECRETS`
  (shadow, /etc/ssh, TLS, Caddy, DB data, /var/log, /home; only when they exist) + `HOME_SECRETS` + `infra.json` /
  `team/`. Gotcha: a `denyRead` on `$HOME` with `allowRead` inside breaks bubblewrap's mounts ("Can't create file
  .claude/settings.json") => entry by entry; a deeper deny wins over `allowRead`. Outside runs
  (`MAXXING_AGENT_OUTSIDE=1`) drop `--allowedTools`; `agents.import` warns about `tools` (`allowed`). Mail: the send
  card of a cut message has no Send button, the E-mail page shows the whole text (`TEXT_PAGE`) + "Show all" before
  Send; a new IMAP/SMTP host or user clears the stored password. `feed.PRODUCT_SOURCES` refused as webhook names.
- Docs only: community library (PR #48) in 12/13/14 and the `maxxing-extension` skill; the site side
  (`/community`, API key, `publish.md`) lives in the cloud repository.

## 2.0.0-alpha.126 - 2026-11-07

- Release preparation for `main` / `stable` (beta a113-a125 go out together). `upgrade_notes(old, new)`
  (`cmd_core.py`) keeps `old < v <= new`: an install at a123/a124 would skip the notes of a113-a122, so
  `docs/upgrade/2.0.0a126.md` gathers their steps (global CLAUDE.md rows, help index rows, Telegram modes, sandbox,
  `health_feed`), each checked first so a re-run changes nothing. Same reason for the CHANGELOG summary at the top:
  "What's new" shows only the entries above the last version seen. Telegram: `gateway.mode()` picks `simple` for a
  chat without any thread at the first start; the note offers `threads` back. Help template rows 09/11/27/32
  updated; 09-telegram heading renamed (`#threads-one-per-open-session`: the docs site slug of "Threads = open
  sessions" differed from GitHub's).

## 2.0.0-alpha.125 - 2026-11-07

- Infra page redesign, front end only (no API change): `features/infra/places.ts` (place of a resource: `location`;
  a domain takes the place of its linked non-domain resources, else `details.hosted_by`, else `none`; tiers
  own/hosted/none, server names and unknown places `sensitive`) and `TypeView.tsx` (blocks per place, `MixBar`,
  place chips, 40 rows then "Show N more"). `InfraPage.tsx`: inner `InfraNav` (sticky bar on desktop, chips on
  touch), new `problems` tab, overview as a type x place table (`infra-matrix`), `?at=<place>` next to `tab`/`id`;
  old `/infra?id=` and `?tab=servers|domains` links still work, an unknown `tab` falls back. Test ids
  `infra-card-*` and `infra-sources` gone (new: `infra-nav`, `infra-tab-<id>`, `infra-place`, `infra-matrix`).
  Presentation mode: `Sensitive`/`useMask` on names, subtitles, projects, place names, details, notes, ids, server
  settings and source errors. `LOCATION_ICON` removed (unused).

## 2.0.0-alpha.124 - 2026-11-07

- Released from `main` (beta-only a113-a122 still stay on `beta`). Holds Radar's hunt of 07/11 (45 findings) and
  issues #41-#43: update file lock for the whole run + in-progress mark dropped on early failure; pcbridge pairing
  under one lock, per-download temp file, action log lock + atomic write, binary frames ignored, frame-limit failure
  fails waiters at once, old chrome-devtools-mcp stopped; license/cloud answers capped at 1 MB with a 30 s deadline and
  nesting guard (bad_answer); videos remember unreadable files and share one ffprobe; thumbnails cache failures 10 min;
  backup restore caps (5 MB / 500 MB), git lock cleanup, bad_ref; MCP check 4 folders at a time; voice Whisper
  revision from deps.toml; log compaction survives lone surrogates; uninstall cron marker; installer PORT base 10;
  ui-kit `<option>` colours.

## 2.0.0-alpha.123 - 2026-11-06

- Released from `main` without the beta-only work (a113-a122: Agents, groups, e-mail, secret files): those numbers
  stay on `beta`. Holds: `sent_items` in session data (service.py `_sent_preview`, shown by Thread.tsx, counted by
  Column.tsx `checkSent`), install.sh `SELF_DIR` computed before `cd /`, Radar audit fixes (proxy: 128 places per
  source address, head size cap, domain with trailing newline; MCP OAuth non-ASCII redirect; default model check;
  CRLF in the code editor; CSV 200 columns; linear git/infra block and fence parsing; touch targets), pageData
  `staleTime` function (tsc -b fix).
## 2.0.0-alpha.122 - 2026-11-06

- Final Agents + E-mail audit of 06/11 fixed on beta (no version of its own): `imap._raw` reads headers the parser
  rejects (`_hdr`/`_addrs` never raise, a bad row is listed without them), headers cut at 16 KB / address lists 64 KB
  before parsing, adjacent encoded-words joined, text/calendar listed as `invite.ics`, `attachments_more`; mail turn
  text built inside `agents.EVENT_MAX` (headers of every mail first, then bodies in what is left, only those fetched).
  send: any SMTP answer = refused (count given back), `sent_unknown` only for a cut after the final ".", body written
  in 64 kB pieces with a per-write timeout, a confirmed send leaves a `result` mark so unstick never re-offers it,
  approvals on the mail pool (`api.mail.run_on_pool`), IDN domains as `xn--`, UTF-8 local parts need SMTPUTF8, forward
  over 50 attachments refused, quoted original cut at 200,000 chars. Agents: `writable` stays inside the topic once
  resolved, `*.` wildcards need two labels (shared suffixes refused), `keys list` in an agent turn = its own text keys,
  sources `mail` / `infra` reserved, `mail attachment` never overwrites (`name (2).ext`, `--force`, reserved names),
  BrokenPipe exits 141, trash restore through a symlinked workspace, `write --reply --send` checks every Reply-To
  address. Telegram: the rest of a long reply split by Telegram follows its first part (`_split_rest`). Infra: sp=
  weaker than p=, invalid parent DMARC, SPF `redirect=` ignored with `all`, loops, the mailbox's SMTP server in the
  SPF suggestion. Web: nothing typed during a draft save is lost, Send waits for the new draft, answered target tied
  to its mailbox, one tab per kept message, presentation mode masks the Agents project tooltip.
- E-mail audit of 06/11 fixed on beta (no version of its own): parsing never raises (`imap._parse`, `_walk` iterative,
  40 levels / 1000 parts, charset fallback alias -> utf-8 -> cp1252 -> latin-1, iso-8859-1 read as cp1252, bidi stripped
  in `_line` and names, message/rfc822 listed as `<Subject>.eml` via `part_at`, linear `strip_blocks`, inline images
  capped 3 MB / 8 MB / 30); poll writes turns to `pending.json` and the position before starting agents, errors mail by
  mail, `retry_pending` one by one, `mail_busy` folders wait for the next check; mail work on its own pool
  (`api/mail.py` `MAIL_THREADS` 8), per-account lock 30 s / 2 waiters -> 503 `mail_busy` + Retry-After, IMAP timeouts
  15 s connect / 25 s I/O, `DOWN_S` 60 s fast-fail, UID list cached on UIDVALIDITY/UIDNEXT/EXISTS, one `_expunge`
  (UID EXPUNGE or flags saved and restored), special-use roles first, Gmail archive to \All, inline PDF without CSP
  sandbox, accounts.json under `mail-accounts` lock, UTF-8 AUTHENTICATE PLAIN, SMTP AUTH needs 235; send: `sent_unknown`
  (409) after DATA, Bcc kept in draft + Sent copy, decoded names in reply/forward, one download per forward (`part_at`,
  rfc822 embedded, never base64), names/types sanitised, reply-all dedupe, a Reply-To other than From never becomes a
  contact, CLI `read` shows Reply-To + caps at 20k (`--max`, `--full`), Infra `dmarc_inherited(_none)`, `spf_neutral`;
  web: drafts keep attachments, one send at a time, autosave (localStorage + IndexedDB for files), `<bdi>`,
  presentation mode, narrow toolbar "…" menu, keyboard rows, accounts error screen. Tests: test_mail_parse.py,
  test_mail_connection.py, test_mail_send.py (+ agents/infra).

- Secret files in the Keys vault (issue #29). New module
  `vault_files` (INTERNALS.md): bytes in `STATE/secret-files/<NAME>` (700 / 600, atomic via same-dir temp +
  `os.replace`), metadata in secrets.json `vault_files` `{filename, size, sha256, note, expose, updated}`. 1 byte to
  1 MiB, a name is a text key or a file (`name_taken`; `vault.put` checks it too, `PUT /api/secrets/{name}` answers 409
  for it). API `GET /api/secret-files`, `PUT /api/secret-files/{name}` (raw body + query `note`, `expose`, `create`,
  `filename`; no multipart so the 1 MiB `bodylimit` applies; empty body = metadata only), `DELETE`; nothing returns
  the content. `exposed_files_env()` ({NAME: path}) merged with `vault.exposed_env()` in `spawn._exposed_vault` and the
  `crons._job_env` fallback. CLI `keys put-file|get-file|delete-file`, `keys list` marks files (`--json` adds `kind`,
  and `filename`, `size`, `sha256` for files); the three are refused in agent turns. `spawn.protected_paths` adds
  `STATE/secret-files/**`; `backup.PRUNE_DIRS` adds `secret-files`; `maxxing init` re-applies mode 700.
  `changelog.parse` skips a `## Unreleased` section (not shown before the maintainers give it a version) and
  `test_all_updates_in_settings` counts versions only. Tests: `tests/test_vault_files.py`.
  Web: "Files" card under the keys in Settings -> Keys (`sections/KeyFiles.tsx`, hooks `useSecretFiles` /
  `usePutSecretFile` / `useDeleteSecretFile` in `queries/secrets.ts`, type `SecretFile`); `api.request` sends a `Blob`
  body as `application/octet-stream`; error codes are mapped to `keyfiles.err.*` texts, the 1 MiB limit is also checked
  in the browser; the mock serves `/api/secret-files` (octet-stream bodies are no longer parsed as JSON).

## 2.0.0-alpha.121 - 2026-11-06

- Attachments of agents and groups: `agents.checked_attachments(base, files)` (≤ `ATTACH_MAX` 10; each a regular file
  under `<base>/attachments/`, `realpath` = the lexical path below that folder, so no link below it; the workspace
  itself may sit behind one) for `POST /api/agents/.../run` (`attachments`, files only = "See the attached files.")
  and `agent_rooms.say(path, text, attachments)`. Uploads: an agent's through `/api/uploads?path=<agent>` (topic_dir
  takes an agent path), a group's through `POST /api/agent-groups/{p}/{g}/uploads` (`agent_rooms.attachments_dir`).
  `service.month_dir` (used by `uploads_dir`) refuses `attachments/` or the month folder as a symbolic link (a
  sandboxed agent writes its own folder). `agent_guard.locked_paths` adds `<agent>/attachments` and `<topic>/attachments`
  (created; also when `writable` names them: denyWrite wins) to the read-only paths (`Edit(/…/attachments/**)` too), and `TOPIC_LOCKED` gets `attachments` (a sandboxed agent with
  `writable: ["."]` no longer writes the topic's uploads: no swapped file read by the owner's sessions, no link to
  race an upload through). `checked_attachments` refuses an `attachments` folder that is a link; `month_dir` turns an
  OSError (a file in the way, a missing parent) into `400 bad_path`. Thread `run` and group `message` items keep `attachments`; a member gets the files of the owner's
  message as session attachments only the first time it sees it (`_origin_files`, by `since`), their paths in the text
  every time (`_files_note` in the framed history).
- Search: kind `group` (`search._index_groups`, key `g:<group path>`, with the sessions at every refresh while
  `agents_page` is on: one stat of the room and of group.json, only the new lines read - sig `{ino, offset, group}`;
  a rewritten room or a changed group.json starts over; Agents off drops the rows). `api/search` leaves `group` out
  while Agents is off (only `group` asked: no results). Palette: agents and groups as static commands (`useAgents` /
  `useAgentGroups`, loaded when the palette opens and Agents is on), `group` hits open the group page.

- Mail outbox: `POST /api/mail/{acc}/draft` on a waiting agent draft calls `outbox.draft_saved` (row `saved` moves to
  the new uid, `data.changed` = true, feed event resolved); `approve` refuses a changed row (`changed`) and ends a row
  whose draft is gone (`imap.has`, IMAP errors count as present). `store.outbox_data` updates only waiting rows.
  `maxxing mail write --forward` stores `forward.names`; the request body lists them ("Attachments (n): ...").
- `send._count_lock` is a `config.ProcessLock("mail-sent-count")`: the daily cap is counted under a flock shared
  by the server and `maxxing mail write --send`.
- Mail check (`mail/poll.py`): the excerpt comes from `imap.excerpt` (`BODY.PEEK[]<0.256 KB>`, text/html of the
  first bytes) instead of `imap.message` (whole mail with attachments). A folder whose position `at` is older than
  `STALE_S` (6 h, or 3 intervals) is looked at as a first check. `retry_pending` drops the held mail when Agents is
  off and re-filters it with the agent's current grant (`watchers` + `_matches`). The check writes and fires nothing
  once the account is gone (`_still_there`). `tests/fake_imap.py`: partial `BODY[]<0.N>` and `(UN)DELETED`.
- `mail.delete_account` calls `agents.drop_mail(acc_id)`: the account leaves every agent's `mail` list (under
  `agents._lock`), so a re-added address (same `_slug` id) has no grant.
- Agents: `on_turn_end` drops a budget hold only if it was made before the turn's `finished_at`
  (`_release(path, sid, ended)`): a hold written by the runner for the next queued turn of the same session
  (mcp_auto continuation, compaction, typed message) stays until that turn ends.
- Agents: `run_settings` returns the owner note as `system_note` instead of a second `--append-system-prompt`
  in `args`; the runner puts it in the one flag of `spawn.agents_args` (Claude Code keeps only the last flag,
  so agents had lost the foreground-subagents rule and the mcp_auto hint).
- `service.last_assistant_text(sid, turn_only=True)` stops at the turn's user message; `agents.on_turn_end` uses
  it for a failed turn, which then reports the session error instead of the previous turn's answer.
- Agent limits: `clean(strict=True)` (create/update, API and CLI) refuses a limit that is not a number, above its
  maximum, or negative where 0 = no limit (400 `bad_limit`); below a non-zero minimum it is still raised to it.
  Not strict (a hand-edited agent.json), a negative budget / rate takes the default instead of 0; a positive
  budget never rounds to 0 (floor 0.01).
- `agents.Debouncer.add` stops keeping texts once a batch holds `EVENT_MAX` characters (what `frame` sends) and
  counts the rest in `dropped` (saved in `_feed.json`); `flush_due` numbers events out of the full count and
  says how many were not shown. A busy agent's batch no longer grows and is rewritten without bound.
- `agents.thread` parses an agent's thread file once per (mtime_ns, size) (`_threads`, up to 200 files): GET
  /api/agents no longer re-reads every thread on each call. The cached messages are shared: never change them.
- Agents: an `agent.json` that exists but does not parse (or is not an object) loads as `enabled: False, sandbox: True,
  broken: True` (`_parse_file`), shown as `broken` by the API (banner on the agent page), alerted by `check_alerts`
  (ref `agent:<path>#broken`); `update()` and `add_webhook()` answer 409 `broken` instead of saving defaults over it.
- Agent webhooks: a feed trigger whose `hook_id` is no longer a feed hook is left out of `_feed_agents()` (scan and
  backlog), and `maxxing feed post` from an agent turn refuses such a trigger's source. `add_webhook()` re-attaches
  that dead trigger (same id) instead of appending a second one, refuses 409 `too_many_triggers` before creating the
  hook, saves under `_lock` (strict clean, hook removed if the save fails), and builds names with
  `feed.clean_source` (base cut to keep the `-<n>` suffix inside 40 characters).
- Feed trigger `source` is normalised like `feed.clean_source` (lower case, other characters -> `-`, 40 max) in
  `_clean_trigger`; strict refuses what cannot be cleaned.
- `agents.remap()` moves the debouncer's waiting batches (and `_feed.json` `pending`) of the renamed prefix.
- Agent state in the Trash: `workspace._delete` calls `agents.to_trash(paths, item)` (agent, topic or project
  delete): `<state>/agents/<key>.json/.jsonl` move to `<item>.agents/` with `crons.json` (ids of their jobs).
  `trash.restore` calls `agents.from_trash` (keys remapped to the restored path, jobs back via `crons.restore_job`
  with `topic_path` remapped); `_remove` deletes the box. `agents.create` drops leftover state of its key. A restored
  agent whose name is taken gets a slug name (`<name>-restored`, `_free_dir_name`), not `<name> (restored)`.
- `agent_format.parse_md`: YAML block values (`key: >` / `|`, with chomping) are read from their indented lines;
  the description is found in the body with whitespace normalised (an exported wrapped first paragraph is not added twice).
- Sandboxed agent turn (`agent_guard.sandboxed_turn()`): `maxxing agents show` refuses another agent and drops
  `webhooks[].url`; `agents list` gives `path` + `display_name` only; `feed list` (`cmd_feed._list`) keeps the sources
  of the agent's feed triggers (events and `sources`, no `pending`).
- Approvals: a request whose stored input differs from the real one (`approval_mcp.clip` cut a string, keys or items)
  gets `clipped: true` (also in `approvals.public`); `approvals.decide(allow)` answers 409 `clipped`, the feed event
  and Telegram offer Open / Deny only, the card disables Allow. The MCP's timeout now takes `<state>/.approvals.lock`
  (the flock of `ProcessLock("approvals")`) and writes `timeout` only if the request is still pending.
- `agent_guard.private_paths` also hides `projects/<p>/groups/<g>` of the groups the agent is not a member of (read
  from group.json) and every `groups/.kept-*` folder.
- Template `sales` no longer suggests `STRIPE_SECRET_KEY` (a full key; `STRIPE_RESTRICTED_KEY` stays).
- `POST /api/agents` takes `template` (id): the server starts from `agent_templates.fields()` like the CLI's
  `--template` (domains, writable...), the body's fields on top; the creation sheet sends it.
- Telegram -> agents: `_agent_lane` gathers the pieces of one gesture per `chat:thread|agent` (`AGENT_GATHER` 1.5 s,
  `MEDIA_GROUP_MAX` cap) into one `_agent_message(msgs, path, texts)` -> one `agents.fire`. `_agent_parts` splits a
  message into the owner's words (`prompt=`) and outside data (`text=`: forwards, quotes of a message neither the bot
  nor the owner wrote) -> framed + `MAXXING_AGENT_OUTSIDE`; with outside data `reply_to` is not used (a continued
  session keeps its own env). `agents.remember_telegram` / `telegram_reply_to` take `chat` (keys `"<chat>:<id>"`; old
  bare keys are no longer matched). Alerts: body over `ALERT_BODY` (1500) gets the `alert_cut` marker and only
  `danger` / link buttons (the callback refuses the others too); `ev["attachments"]` (names or {name}) listed.

- Agent groups (`agent_rooms.py`): `room()` reads the jsonl from the end (`_tail`), so `public()` / the list no
  longer parse a whole room for its last message; a room past `ROOM_BYTES` (2 MB) is trimmed to half of it (and
  `ROOM_KEEP` lines), not to 1,000 lines that could stay over the threshold. `GET .../messages?after=<at>`: the
  group page asks only for the new messages. Group events no longer send `workspace` on the bus (only create,
  delete, rename: `_invalidate(tree=True)`).
- Groups: `update` drops former members whose agent is gone (`dropped` in the answer) instead of `unknown_member`;
  `say` picks the lead / last speaker / first member among live agents only and posts the same owner text once
  within `SAME_SAY_S`; `remap` rewrites the message authors; a project delete moves `rooms/<p>__<g>.json(l)` into
  the trashed group folder as `.room.json(l)` (`agent_rooms.deleted_with`), `trash.restore` puts them back
  (`agent_rooms.restored`, paths swapped and fresh sessions under a `-restored` name); `create` drops stale ones.

## 2.0.0-alpha.120 - 2026-11-05

- E-mail page (`mail_page`, off by default; picked from the 2.0.0a68-era branch): `maxxing/mail/`
  (`__init__` accounts + detection + SMTP sign-in, `imap.py` live IMAP with one pooled connection per account,
  `send.py` writing), `api/mail.py` (`/api/mail/*`, docs/dev/API.md#mail), `cmd_mail.py`. Accounts in
  `<state>/mail/accounts.json`, password = vault `MAIL_<ID>_PASSWORD` (expose false). Writing: plain text,
  `compose(mode=reply|replyall|forward|draft)` returns the starting fields (signature block then quote), `send()`
  goes through the account's SMTP (`open_smtp`: AUTH PLAIN by hand for non-ASCII credentials, smtplib only sends
  ASCII), appends to Sent unless the SMTP host files it (`AUTO_SENT`: gmail, office365, outlook), flags the replied
  message `\Answered`, drops the draft it came from (`imap.drop`, drafts folder only). Drafts: `imap.append_draft`
  (APPENDUID, else SEARCH by Message-ID). Caps: `MAX_RECIPIENTS` 20 a message, `mail_send_per_day` (config, default
  100) recipients a mailbox a day in `<state>/mail/sent-count.json` (given back when the send fails), 25 MB of
  attachments. `maxxing mail write` saves a draft unless `--send`. Tests `tests/test_mail.py` (+ `tests/fake_smtp.py`;
  `MAXXING_TEST_IMAP=host:port:user:pw` runs a round trip on a real IMAP server). Mail is never put in the feed.

- E-mail for agents (`maxxing/mail/{access,poll,outbox,store}.py`): agent.json `mail` = `[Grant]` (`access.clean_grants`,
  called by `agents.clean`; empty by default), enforced in agent turns by `cmd_mail.Guard` (identity from
  `agent_guard.agent_turn`, never the environment): mailboxes of the grants only, rights read/draft/move/mark/send,
  `senders` filter = sender seen only when `from_verified` and matching (lists: IMAP `FROM` narrowing + check, up to
  `imap.SCAN_MAX`), recipients limited to the same patterns, `read` never sets `\Seen`, attachments saved only in the
  agent folder / `writable_dirs` (not `locked_paths`), `--attach` only from its topic (not `secret_paths` /
  `private_paths`), `add` refused. `from_verified` (`access.verified`): only the topmost `Authentication-Results`
  counts, and only when its authserv-id's base domain is trusted (`access.trusted_servers`: the account's IMAP/SMTP
  hosts + MX + `PROVIDER_ALIASES`, or `auth_servers`); dmarc=pass header.from, or dkim/spf pass aligned with the
  From domain. `approve_send` always|new|never: `outbox.queue` files a draft, keeps the fields + files in
  `<state>/mail/outbox/<id>/`, posts a feed event (source `mail`, ref `mailsend:<id>`, actions allow/deny/open,
  `feed.HANDLERS["mailsend"] = "mail.outbox"`); `approve` claims the row once and sends with `draft` (dropped),
  `deny` drops the draft, `draft_done` ends it when the owner sends / deletes the draft from the page. "new" =
  recipients absent from `contacts` (senders seen by the checks, past recipients) and not the replied sender.
  `<state>/mail/mail.db` (`store.py`, a cache set aside when unreadable): poll positions (UIDVALIDITY, last UID),
  newest 500 mails per mailbox, contacts, `seen_by` (by Message-ID, else folder#uid, 90 days), outbox. Checks
  (`poll.py`, server loop in `api/mail.py` every 30 s): mailboxes whose `poll_min` (5/10/30/60, default 10) is over,
  INBOX + folders watched by triggers; first check of a folder (or new UIDVALIDITY) only notes the position; new
  mail matching an enabled trigger of an enabled agent (grant senders, trigger senders / subject, not the mailbox's
  own address) -> one `agents.fire(trigger="mail:<id>", text=..., wait=True)` per agent and check (outside text:
  approvals forced unless `trust_outside`), busy -> `<state>/mail/pending.json`, retried next tick (a day at most).
  API: `/api/mail/refresh`, `/all`, `/outbox`, `/outbox/{id}/send|deny`; accounts + `poll_min`, `auth_servers`,
  `last_check`, `agents`, `waiting`; rows + `from_verified`, `message_id`, `seen_by`. CLI `maxxing mail refresh|outbox`;
  `maxxing mail` allowed in sandboxed turns (`CLI_ALLOWED`, filtered by Guard). `maxxing agents create --mail
  MAILBOX`; templates `mail-sort`, `mail-support`, `mail-invoices` (`mail` field, `fields(..., mail_account)`; the UI
  asks the mailbox). UI: agent settings E-mail section (`AgentMail.tsx`), mail triggers in the agent's triggers,
  mailbox picker for mail templates, E-mail page: Refresh, last check, All mailboxes, outbox banner, seen-by faces,
  verified sender, `?account=&folder=&draft=` and `?add=` links. Tests `tests/test_mail_agents.py`.

- E-mail hardening (before beta). `maxxing mail` runs as root outside the agent's sandbox, so: `imap._search_args`
  turns every control character into a space (a CR/LF inside `UID SEARCH TEXT "..."` sent commands of its own);
  `Guard.read_file` / `Guard.write_file` check the path of the opened file descriptor (`/proc/self/fd`), never follow
  a final link (`O_PATH | O_NOFOLLOW` handle checked first, then reopened through `/proc/self/fd`; a new file
  `O_CREAT | O_EXCL` relative to the checked folder's fd), refuse non-regular files and a second name
  (`st_nlink > 1`), never create a folder as root (`OUT/` must exist), attachments at most 25 MB (`ATTACH_MAX`).
  Header values (subject, names, addresses, attachment names) lose their control characters (`imap._line`). Sender checks: `access.authserv_id` /
  `_cfws_free` (comments and quoted strings never count); `access.detect` (the base domain topping >= 90 % of the 50
  newest INBOX mails by UID - never the Date: header -, >= 10 mails from >= 3 sender domains, own domain left out;
  samples = `messages.auth_server` + `messages.received` (INTERNALDATE), `store.auth_samples`, noted by the checks,
  `poll._sample` fills them on a new mailbox); `access.sender_check` -> `{state: owner|auto|detected|none, server}`
  (`auto` = `STAMPING` provider hosting the mailbox's IMAP/SMTP servers - not the MX alone; `detected` = one of the
  mailbox's own IMAP/SMTP/MX base domains, samples spanning >= 7 days, offered to the owner), also in
  `MailAccount.sender_check`; `imap.trust` = the owner's `auth_servers` bases, or the `auto` server, else nothing.
  Contacts (approve_send "new") = recipients of what the owner sent from Harness or allowed (`send.send(...,
  contacts=False)` for an agent's own send); the senders of incoming mail and the replied sender no longer count;
  mail.db `user_version` 1 empties `contacts` and adds `messages.auth_server`. `mail read` and the check's event text
  use random markers; mail kept for a busy agent (`pending.json`) keeps the rows (headers + shown texts, 200 at
  most), the text and its marker are built again when the turn starts. In an agent turn: `outbox` lists its own
  rows, `-a` resolves among its mailboxes only, `refresh` only asks the server (`poll.request`:
  `<state>/mail/.refresh-<id>`, due at the next tick; an agent never moves the positions). A new UIDVALIDITY drops the
  cached mails of the folder. `auth_servers` refuses IP addresses. `cmd_mail` and `outbox.feed_action` refuse when the page is off (409 `mail_off`).
  Checks: per-mailbox non-blocking lock (thread set + `flock LOCK_NB` on `<state>/mail/.poll-<id>.lock`; busy ->
  `{skipped: "busy"}`); `imap.new_since` takes the oldest `limit` after `last_uid` (`more` -> `poll._again`, due at the
  next tick); `pending.json` under `ProcessLock("mail-pending")`, text capped at 60 000 chars. Outbox: any exception
  of `approve` puts the row back to `waiting`; `outbox.unstick()` (each tick) turns `sending` older than 10 min back
  to `waiting` with a note; `outbox.forget` ends the waiting rows of a removed mailbox ("Mailbox removed").
  `store.prune` (daily, from `outbox.tidy`): `seen_by` 90 days, contacts 2 years / 5 000 per mailbox. MX through
  `dnsinfo.doh_api()`, a failed lookup cached 5 min (`imap._mx_of`). After SMTP accepted a message, its follow-ups
  (copy in Sent, \Answered, draft dropped) never raise: a sent message never waits again. `/api/mail/accounts`, `seen_by` lookups off the
  event loop; the trust is computed before the IMAP connection is held; `/refresh` reports any error per mailbox.
  UI: sender check line + "Trust <server>" in Edit mailbox, warning under an agent's sender list, Notifications
  decisions refresh the mail queries. Tests `tests/fake_imap.py` (an IMAP server in memory that logs every command)
  + `tests/test_mail_imap.py`.


- Agents' sandbox (`agent_guard`): the rules hook is `python -I -c <boot> hook <path>` (`hook_command`; `-I` keeps the
  agent folder, the hook's cwd, and PYTHONPATH off sys.path). `settings(path, a, approvals)`: with approvals
  (configured or forced for an outside event) `autoAllowBashIfSandboxed` is false and `Bash(maxxing:*)` is no longer
  pre-allowed (asked through the approval tool). `writable_dirs`: "." = the topic's entries but `TOPIC_LOCKED`
  (agents/, CLAUDE.md, CLAUDE.local.md, memory.md, .claude, .mcp.json; denyWrite wins over allowWrite, so agents/
  cannot be denied around the agent's own folder), `agents/...` refused in `_clean_writable`; `topic_edit_denied`
  adds Edit denies (other agents' folders, `agents/*/agent.json|CLAUDE.md|.mcp.json|.claude/**`, topic files).
  denyRead adds the Claude transcripts + history.jsonl, `~/.config`, `~/.local/share` (allowRead back: `READ_BACK`,
  Claude Code itself and uv's pythons/tools), other projects / topics / agents, `.env` globs of the topic
  (`private_paths`). Subagent prompt frames memory.md as notes. install.sh no longer loads the bwrap AppArmor profile:
  `sandbox-setup` or `ensure_profile()` on create / sandbox on (root, best effort). Not run live here: this server's
  units cannot nest user namespaces (apply-seccomp setgroups EPERM), checked from the generated settings + the
  Claude Code 2.1.306 setting texts ("allowRead ... takes precedence over denyRead", "denyWrite takes precedence over
  allowWrite", denyRead globs expanded on Linux, write globs skipped).
- Agent turn identity: `agent_guard.agent_turn()` -> `{path, depth, tampered}` read from the session meta of the turn's
  unit (`turn_meta()`, cgroup `maxxing-<sid8>[-N].service`; the suffixed retry name is now matched too), not from
  `MAXXING_AGENT*` (env only outside a unit: direct spawn, the owner's shell). Used by `keys get`, `agents send|run`,
  `feed post`; `check_cli` refuses a turn whose env disagrees with its record.
- `maxxing agents run` from an agent turn = `send` (depth + 1, not itself, trigger `agent:<sender>`, text as data).
- `feed post` from an agent turn refuses BUILTIN and feed hook sources; events get a `hops` column (poster depth + 1),
  `Debouncer` keeps the max per batch and `flush_due` fires with it, so feed chains stop at `MAX_DEPTH`.
- Approvals: `approvals.summary(tool, input) -> (text, whole)`; `whole` is False when the line is cut at `SHORT_MAX`
  or leaves keys out (`_MINOR` keys aside). Not whole: the feed event gets `open` + `deny` (no `allow`, so
  `feed.act(..., "allow")` is a 400) and the older Telegram message Deny only; `_on_approval` refuses an `allow`
  callback for it.
- Telegram `_on_alert`: a press counts only when notes.json `al:<id>` names this chat + message id (stale
  buttons after a recreated feed.db, where ids restart, lose their buttons instead of deciding a new event).
- `approvals.prime()` announces a pending request of a running turn that has no `approval:<id>` feed event yet
  (written while the server was down): feed event, thread message, Telegram; `_feed_new` returns True / False / None.
- `approvals.decide` and the watcher's expiry read-check-write under `config.ProcessLock("approvals")`: two answers at
  once (web + Telegram) = one 200, one 409 `not_pending`.
- Telegram `_alert_send_sync`: once the note `al:<id>` is stored, the event is read again (`feed.get`) and the message
  edited at once if it changed meanwhile (an `update_alert` during the send found no message to edit).
- Telegram reply map: `state_dir('telegram')/messages.db` (SQLite `msgs(k, v, at)`, WAL) instead of `messages.json`
  (taken in and deleted on first use), one connection per process (`synchronous=NORMAL`, reopened when the file is
  replaced). A bound send was a 520 KB read + rewrite (62 ms at 5,000 entries), now ~0.2 ms;
  same limits (MSGS_KEEP newest, MSGS_DAYS). `_msgs_all()` lists it.
- Feed: `feed.db` gets partial indexes `events_agent` (`agent IS NOT NULL`, for `agent_alerts`) and `events_pending`
  (`at WHERE actions IS NOT NULL AND resolved IS NULL`), created on open. `list_events` returns `pending` on the first
  page only (no `before`); `pending_count()` is kept like `source_counts()` (`_kept`: feed.db/WAL stamp + minute).
  50k events: first page 28 ms -> 0.6 ms, "Load more" 32 -> 0.5 ms, cold pending count 49 -> 0.4 ms, `agent_alerts`
  3.3 -> 0.5 ms.
- Feed: `post(group=)` never folds into a resolved event; `resolve(ref)` ends every open event of the ref (returns
  the newest); `act` seen/open (not by Telegram) and `mark_read` call `update_alert` for the open alerts they read.
- Agents list speed: `agents._agent_metas()` = one pass over the session metas grouped by agent path (kept until
  the sessions folder's mtime moves, `_by_agent`), shared by the counts (`agents._session_stats`, archived sessions
  only counted) and `status(path, metas)` (thread parsed once). `list_agents(counts=False)` for the background passes
  (feed scan, alerts). The runner's `run_settings(session=)` reads only the metas written in the last 25 h
  (`day_cost(cold=True)`). `workspace.topic_permission_mode` reads agent.json instead of `run_settings`. 3,000
  sessions / 30 agents: `list_agents(with_status)` 3.3 s -> 0.28 s (0.19 s of it = `feed.agent_alerts`), `get` 190 ->
  8-15 ms, background list 115 -> 15 ms, runner cold 156 -> 36 ms (90 % of sessions older than a day).
- Agents budget: each run holds its `--max-budget-usd` in `<state>/agents/<key>.json` `held: {sid: {usd, at}}`
  (set by `fire` at the start, then by `run_settings(..., session=sid)` in the runner, dropped by `on_turn_end` or once
  the session is no longer running). `gate()` returns `busy` when spent + held reaches the budget; `fire()` runs gate +
  start + the `run` post under `agents._lock` (runs per hour race too); `fire(wait=True)` (feed) returns `busy`
  without posting and `flush_due` retries after `BUSY_RETRY_S`.
- Session `days` keys (Stats, agents' daily budget) are days of `config.timezone` (`store.day_of`), no longer
  of the system zone; agent run titles and thread context times too (`agents._local`).
- Agents feed triggers: `_feed.json` = `{last_id, pending, off?}`. A missing `last_id` (not 0) means "never
  scanned"; `pending` = the debounced batches (`Debouncer.dump/load`, reloaded at the first scan of the process);
  `off` is set by the server loop while Agents is off (`agents.pause_feed`), and the next scan skips the events since
  then (`agents.skip_backlog`: one `note` with `status: skipped_off, events: n` per agent that had matches).
- Agents bus topics are finer: `agents_layout` (save_layout: the layout query only) and `agents:<path>` (thread
  post, mark_seen, feed event of an agent: list + that agent's detail + thread, `busKeysOf` in keys.ts). The plain
  `agents` topic (create, patch, delete, crons) no longer refetches the templates nor the sandbox check.

## 2.0.0-alpha.119 - 2026-11-05

- Agent groups (`maxxing/agent_rooms.py`, `api/agent_groups.py`, API.md#agent-groups, INTERNALS.md#maxxing.agent_rooms):
  `projects/<p>/groups/<g>/{CLAUDE.md, group.json, files/}`, room `<state>/agents/rooms/<p>__<g>.{jsonl,json}`.
  Routes `/api/agent-groups` (prefix apart from `/api/agents/{p}/{t}/{a}`: no clash). Bus `agent-groups`,
  `agent-groups:<path>`. `group.json` added to `backup.ALWAYS`.
- `agents.run_settings(path, outside, session, group="")`: the runner passes `MAXXING_AGENT_GROUP` from the session env;
  a group turn gets the group's `files/` as a writable folder and is outside when it is a hand-over and the group's
  `trust_members` is off (`agent_rooms.turn_outside`, per session id).
- `agents.on_turn_end` reads the session meta env (the public session has none) and hands group turns to
  `agent_rooms.on_turn_end`; their thread `run` / `result` lines carry `group`; no Telegram message for them.
  `_runs_last_hour` skips `run` lines with `group` (a group's turns are bounded by its own limits).
- `agents._git_exclude(dir, sub="agents")`: also used for a project's `groups/`.
- `agent_guard.AGENT_OWNER_ONLY` += `group` (`maxxing agents group ...` refused in every agent turn).
- CLI `maxxing agents group list|show|create|say` (cmd_agents.py). Fake claude: `REPLY_AS <folder>: <text>` (`AT:` -> `@`).
- Web: `features/agents/{GroupPage,GroupForm}.tsx`, groups at the top of their project in `AgentsList`, routes
  `/agents/groups/new` and `/agents/groups/:project/:name`, `lib/queries/agentGroups.ts`, showcase `agent-groups`.
- Members' `handle` (@name in the group, stored in group.json): folder name, else (same folder name twice) the
  display name slugified, else `<topic>-<folder>`; kept when a member stays (`update`). CLI `group update`.
- Web: quick create (tick agents, Create; name made from theirs), "Or set it up with Claude" and "Edit with Claude"
  (prefilled sessions), "New group with this agent" on the agent page (`/agents/groups/new?with=<agent path>`).
- `web/src/styles/globals.css`: `@source not '../../dist'` - Tailwind no longer scans the committed build (bytes of
  its .br files made every other build differ).
- Docs: `docs/user/31-agent-groups.md`, links from 01, 15, 16, 17, 30, README, help index, skill `maxxing-agents`.

## 2.0.0-alpha.118 - 2026-11-05

- Audit of a117 (`proxylisten.py`). `guarded_protocol(port)` = uvicorn's HTTP protocol (httptools or h11) with, on the
  proxy socket only (`sockname` port): a request head within `HEADER_TIMEOUT` 10 s (re-armed after each response; a
  response being sent is never cut), `MAX_CONNECTIONS` 512 (`open_now`; a websocket upgrade leaves the count, its
  protocol owns `connection_lost`). Before: half-sent heads stayed open forever (~20 KB each, any container).
  `PRIVATE_NETS` allow-list (is_private let 6to4, Teredo, 169.254, 198.18, ::ffff: through). `DOMAIN` = install.sh
  `valid_domain` (a `--domain` with backticks wrote a Traefik rule). `--new-secret`; `disable()` drops the secret and
  `reverse-proxy.conf`; `saved()` for the ufw rules of an old address. Gate keeps one X-Forwarded-Proto (the value
  used; security.py reads it for Secure cookies). install.sh: docker0's address (`|| true` under pipefail), proxy
  path only with Docker (Traefik on the host gets the 127.0.0.1 block), `dockerd*`, `setup_access` runs
  `maxxing proxy off` outside domain mode.

## 2.0.0-alpha.117 - 2026-11-05

- `proxylisten.py` + `maxxing proxy on|off|status`: config `proxy_listen` ("HOST:PORT", private address only, default
  172.17.0.1:8790) opens a second socket in `cmd_serve` (uvicorn.Server with two sockets, IP_FREEBIND so it binds
  before Docker brings docker0 up; without `proxy_listen` the old `uvicorn.run` path). `Gate` (ASGI): on that socket
  every request needs `X-Maxxing-Proxy` = secrets.json `proxy_secret` (403 / websocket close 1008 otherwise, header
  stripped), then client = last X-Forwarded-For entry, scheme from X-Forwarded-Proto; X-Forwarded-For is kept so
  `api/pc.py` never sees it as local. Traefik block (0600) in `<state>/reverse-proxy.conf`, denied to Claude. With
  ufw active: allow from 10/8, 172.16/12, 192.168/16 to that address and port (removed by `off` and uninstall).
  install.sh `proxy_snippet`: docker-proxy / traefik / unnamed listener with Docker on 80/443 -> `maxxing proxy on`;
  `secure_server` re-runs it after turning ufw on. Generic on purpose: no code for a given tool.
- Radar fixes since a112 (crons day/month names and weekday ranges, file viewer link, path scan, plan chip size).

## 2.0.0-alpha.116 - 2026-11-04

- Telegram modes: `config.telegram.mode` = `simple` | `threads` | `mirror` (`gateway.mode()`; no default in
  `DEFAULT_CONFIG`: a config without it is `threads` - `mirror` when `mirror_web` + `mirror_web_chosen` - if the chat
  has session or special threads, else `simple`; `_settle_mode()` writes it at gateway start and at link).
  `uses_threads()` = threads modes and `threaded()`; `mirror_web()` = mode `mirror`. Simple: `sync_threads_with` does
  nothing, `reopen_thread` returns None, `new_session(flat=True)` creates no thread, `_start_new` binds the "where?"
  message, `w:<key>:s` = "↩ Continue" the last Telegram session (`state.last = {sid, at}`, < `LAST_WAIT` 2 h).
  `set_mode(new, wait=False)` -> `{mode, deleting}` (to simple: `purge_with(call)` deletes session + special threads,
  agents' kept); `PUT /api/telegram/settings {mode}` -> `{ok, mode, deleting}`; `maxxing telegram mode [m]`.
- Reply routing (every mode): `messages.json` (`bind_messages(chat, ids, {sid}|{agent})`, `bound(chat, mid)`;
  `send_html(..., reply_to, bind)`, `send_parts` returns the sent messages, `_send_sync(..., bind)`); `handle_update`
  routes a reply to its session / agent before the new-session flow; `/stop /close /model /status` without a
  reply in simple = the last session (`_last_session`); `/sessions` in simple = `_cmd_recent` (`o:<sid>` posts a card
  bound to the session). `_track(..., reply_to)` (also kept in `replies.json`): status and answer are replies to the
  user's message when the session has no thread of its own; `_with_context` drops the quote of a reply to the bot's
  own message of the same session (`msg["_mx_bound"]`).
- Bell: `rings(session)` (notify, human session, `last_turn.kind == "user"` and `last_turn.source` not telegram /
  cron / system) replaces the test on the session's creation source; posted in the session's thread or the main
  chat, bound; the no-gateway fallback sends to the session's thread too.
- Alerts: `_watch_health` / `_health_pass` (every `HEALTH_EVERY` 60 s, not `HEALTH_SKIP` = `cron_failed`,
  `login_failures`; `state.health = {id: {chat, mid, html, seen}}`; callback `h:<id>` -> `health.mark_seen`), skipped
  when the feed carries the alerts (`feed.act` exists); `post_alert(ev)` / `update_alert(ev)` take a feed event
  (rule `ev.telegram` off|silent|loud, approvals always sent and loud; `open` = URL button; callback
  `al:<id>:<action>` -> `feed.act(int(id), action, by="telegram")`, `notes.json` "al:<id>", dropped once resolved; a resolved `approval:<rid>` event also edits an older `p:` message of that request, and a `p:` tap edits its message itself); approval messages also kept in `notes.json`
  ("p:<id>") so `approval_done` edits them after a restart; approvals and alerts of an agent without a thread are
  bound to the agent.
- Clean-up: texts in `telegram/texts.py` (French duplicates removed, missing `save_failed` added); removed the
  threads-off fallback (`tg["sessions"]`, `_session_for`, `_path_for`, `/topic`, callbacks `s:` / `t:`,
  `state.fallback_path`), the 2.0.0a4 migration (`_migrate_topic_threads`), `notify_topic`, `notify_cron`, the ROOT
  fallback of `_target`, `_set_error`; `twofactor._send` uses `gateway._send_sync`; `_hear()` shared by voice notes of
  sessions and agents; agent messages run in a lane (`_agent_lane`); `_ask_about_event` answers the tap at once
  (`_about_event` in the background, `source=` keyword); `_reply` answers as a reply in the main chat.
  Tests: `mx_state` sets `telegram.mode = "threads"` (older tests), `test_telegram_simple.py`.

## 2.0.0-alpha.115 - 2026-11-04

- Feed alerts: `feed.db` `events` gets `actions` (JSON), `ref`, `agent`, `resolved`, `resolution` (added on open,
  `ALTER TABLE`; index `events_ref`); `feed.post(..., actions=, ref=, agent=)`, `find`, `open_events`, `update`,
  `resolve`, `act` (+ `HANDLERS`: `approvals.feed_action`, `health.feed_action`), `agent_alerts`; `list_events(pending=)`
  + `pending` count. API `POST /api/feed/{id}/act/{action}` (idempotent), `GET /api/feed?pending=1`, settings `health`.
  Built-in sources `agents`, `health`. Telegram contract: `gateway.post_alert(ev)` / `update_alert(ev)` when present
  (`ev["telegram"]` rule hint, requests always loud; buttons -> `feed.act(..., by="telegram")`); while absent,
  `feed_notify` and the request's `notify_approval` / `approval_done` as before (`approvals._telegram` skips them once
  `post_alert` exists).
- Writers: `approvals.scan` (pending -> event `approval:<id>` with Allow / Deny, dedupe), `_note` / `prime` (resolve:
  Allowed / Denied / No answer in time / Expired); `agents.fire` (budget / rate -> one open event each, resolved
  "Runs again" at the next start), `on_turn_end` (failed run grouped per agent, resolved by the next good run;
  sandbox error -> `agent:*#sandbox`), `agents.check_alerts()` (feed trigger whose `hook_id` is gone),
  `health.sync_feed()` (config `health_feed`, `maxxing init`: true for a new install, false for an existing one;
  `cron_failed` skipped). Both every 30 s in `api/feed._watch`. Loop guard: a feed trigger on source `agents` is
  refused, `scan_feed` skips that source. Agent status `alerts` (list badge); feed/agent changes invalidate `agents`.
- Web: `FeedItem` buttons (`FeedActions`, `useFeedAct`) and resolution line; `/feed` **To handle** chip
  (`?pending=1`), dashboard panel "N to handle"; Settings -> Notifications health switch; Agents list alert badge.
- Docs: agents and alerts linked from Settings, Telegram, Crons, Security, Troubleshooting, the help index and the
  `maxxing-feed` skill (built-in sources `agents` / `health`).

## 2.0.0-alpha.114 - 2026-11-04

- Approvals on the Agents page (web only): `usePendingApprovals()` (`GET /api/approvals` without `session`, key
  `['approvals','pending']`); `features/agents/approvals.tsx`: `useThreadApprovals()` folds the `note` of a request
  (same `approval` id) into its `approval` message (`ThreadApprovalBody`: live `ApprovalCard`, then the outcome),
  `WaitingBubble` = the waiting marker of a desk (Classic `Bubble`: a yellow quest "!"; Space `StatusChip`) opening the
  agent's `ApprovalCard`s in a centered `Dialog` (bottom sheet on a phone), closed once nothing is pending; `ApprovalCard` exported (`className`); `useDecideApproval` also invalidates `['agents']`.

## 2.0.0-alpha.113 - 2026-11-04

- Owner-only agent settings: `agent_guard.locked_paths()` (agent `agent.json`, `CLAUDE.md`, `.claude/`, an existing `.mcp.json`,
  topic `.claude/` and existing `.mcp.json`; a missing one would get a placeholder mount that breaks `git add -A`) go to `sandbox.filesystem.denyWrite` + `Edit(...)` deny rules; `check_cli` refuses
  `agents create|cron|webhook|watch|on|off|import|sandbox-setup` whenever `MAXXING_AGENT` is set (sandboxed or not);
  every agent turn gets `--append-system-prompt agents.OWNER_NOTE`; `agents._snapshot()` at `fire()` +
  `_changed_during()` at `on_turn_end` post a `note` (`status: changed`, `files`) when a run changed `agent.json` /
  `CLAUDE.md` (owner `update()` meanwhile sets `owner_at` and is not reported). Verified with a real sandboxed run:
  Edit refused by permissions, `sed -i` EBUSY, `>>` read-only, `.claude/` read-only, CLI refused.
- UI: no dialog to create or change an agent with Claude. `EditWithClaude.tsx`: `draftUrl()` =
  `/sessions?new=1&path=<topic>&prompt=<text>` (a new-session draft of the topic, pre-filled, not sent);
  "Edit with Claude" (agent page) uses the agent's topic + `agents.edit.prompt`. "New agent" opens the CreateAgent sheet
  on `QuickCreate`: project then topic first (prefilled from the list's `?topic=`), then two choices, "With Claude"
  (`useCreateWithClaude(topic)` = `draftUrl(topic, agents.create.prompt)`) or "By hand" (the form on that topic); the
  gallery and the import use the same topic (`CreateStart.topic` from the empty page). The composer takes the focus with the cursor at
  the end on a pre-filled draft (mount or `DRAFT_EVENT`; `prefillDraft` always fires it).

- `agents._git_exclude()`: creating an agent in a topic that is (or sits in) a git clone adds `/<rel>/agents/` to
  that clone's `.git/info/exclude` (worktrees/submodules through `gitdir:` + `commondir`), never a tracked `.gitignore`:
  an agent's turn that commits the blog no longer commits `agent.json`.

Agents (`agents_page`, off by default for new and existing installs; the module works anyway for crons and the CLI): a lasting role in a topic folder
`projects/<p>/topics/<t>/agents/<a>/` (CLAUDE.md role + memory.md + agent.json), see INTERNALS.md#maxxingagents and
API.md#agents. Server core: `maxxing/agents.py` (agent.json validation, `fire()` = the only way in with guards
`enabled` / `usd_per_day` / `runs_per_hour` / hops, a NEW session per start with `source: "agent"`, `cron: true`; thread
`<state>/agents/<p>__<t>__<a>.jsonl`; feed triggers polled from feed.db every 10 s + in-memory debounce; webhook
trigger = a feed hook + a feed trigger on its source; cron trigger = a `kind: claude` job whose `topic_path` is the
agent path, `crons._run_claude` goes through `fire`), `api/agents.py` (`/api/agents...`, 404 `feature_off`). Session
paths gain an optional 3rd level (`workspace._PATH_RE`); rename / delete of a topic carry its agents (state files, cron
jobs, `telegram.agent_threads`). Memory level `agent` (`memory.files()`, skills `memory` / `memory-compaction`),
`agent.json` in `backup.ALWAYS`.
- Telegram: `config.telegram.agent_threads = {path: {tid, name}}` (new default key); `gateway.notify_agent(path, text,
  ok)` (any process: blocking `call_sync`, in a daemon thread from an event loop) creates / renames the thread
  `🤖 <name> · <p>/<t>`, main chat with `🤖 <name>` in front when threads are off; `Gateway._agent_message` turns a
  message there into `fire(trigger="telegram", prompt=text)` (files saved in the agent folder, voice transcribed,
  commands answered with a hint) and answers "⏳ <name> is on it." / the refusal reason (new WORDS keys `agent_*`,
  `AGENT_REASONS`). `_send_sync(..., target=(chat, tid))`; `_forget_thread` also drops agent threads; link to another
  chat / new bot / forget reset them; `_sync_sessions` never deletes them. `topic_label` / `topic_name` know agent
  paths.
- CLI `maxxing agents list|run|send|on|off` (`cmd_agents.py`, registered in `commands.py`): `send` frames the text as
  data, trigger `agent:<sender path>`, depth `MAXXING_AGENT_DEPTH + 1`; `run --data` frames, plain `run` = a task.
- 3rd level elsewhere: `mcp.where_of` adds `agent`, `_project_files` reads `agents/*/.mcp.json`; search indexes agent
  CLAUDE.md / memory.md as memory titled `memory.md · agent <a> (<p>/<t>)`, one file budget per agent (the topic bucket
  skips `agents/`); the importer skips `projects/*/topics/*/agents/**` (an import never plants an agent); stats topic
  rows carry `label` and `agent`; `workspace.describe` returns `topic` / `agent`.
- Product skill `maxxing-agents`; workspace template CLAUDE.md (skill + CLI rows) and help index row (applied to
  existing workspaces by `docs/upgrade/2.0.0a113.md`). User docs `docs/user/30-agents.md`, CLI reference section,
  welcome bullet, README bullet, showcase `agents` (route `/settings/features`).
- Working directory of an agent turn = the agent folder (`create_session(path=<agent path>)`): Claude Code loads the
  CLAUDE.md / memory.md chain from there, and relative paths of the topic need `../..` or a `cd` to the topic. The
  templates' `Edit(./memory.md)` relies on it.
- `agents.create` writes the CLAUDE.md heading with the display name (`# Agent <name>`, was the folder slug).
- Conversation (`fire(..., reply_to=<thread message id>)`, `POST .../run {text, reply_to}`, a Telegram reply to an
  agent result via `remember_telegram` / `telegram_reply_to`): the run's session gets the message
  (`service.send_message`, `run` message with `reply_to`, `continued: true`); a new `manual` / `telegram` / `agent:`
  start gets `context()` = the last `CONTEXT_RESULTS` (3) results, `CONTEXT_CHARS` (500) each, between `THREAD-<hex>`
  markers; cron / feed runs get nothing. `POST .../seen` (`mark_seen`), `POST .../triggers/{tid}/test` (a sample feed
  event on the trigger's source), `agents.trigger_stats` (received count + last per webhook trigger).
- Loop guard: from an agent turn (`MAXXING_AGENT`), `maxxing feed post` refuses (exit 2) a source one of its own feed
  triggers watches (`cmd_feed._self_trigger`).
- `agents.tidy(path)`: archives the agent's finished sessions that were read (session `seen_at` or thread `seen_at` >=
  `finished_at`) and the unread ones beyond `KEEP_UNREAD` (5), never running or unread failed ones; run on `seen` and
  before each `fire`, not when a session is opened. A new message unarchives as usual.
- Outside runs and keys: `fire(text=...)` sets `MAXXING_AGENT_OUTSIDE=1`; `run_settings(path, outside)` forces
  approvals then unless `trust_outside` (`approvals_forced`). `keys` (vault names, max 50) = the only vault entries a
  turn of the agent gets (none by default, exposed or not); `maxxing keys get` inside such a turn answers only for
  them, `set` / `delete` are refused (a speed bump, not a wall: a bypass turn as root could read `secrets.json`).
- Approvals on Telegram: `gateway.notify_approval(d)` posts a pending request in the agent's thread (option
  `telegram`) else in Alerts, buttons `p:<id>:allow|deny` (`_on_approval`); `approval_done(id, status)` edits the
  message wherever the answer came from (message ids in memory: after a restart an old button answers "already" and
  is removed).
- Gallery: `maxxing/agent_templates.py` (support, sales, orders, watch, pr-review, writer, uptime, feedback; en + fr,
  other languages get en), every template `permission_mode: default` + a short `allowed_tools` list (`READ` =
  `Read, Grep, Glob, Edit(./memory.md)` + what the role needs); `GET /api/agents/templates`, `maxxing agents
  templates`, `create --template` (`fields(t, keys_present)`: keys kept only when the vault has them).
- Per-run budget: `run_settings` adds `--max-budget-usd <usd_per_day - day_cost, min 0.01>` when the agent has a
  daily budget, so Claude Code stops a turn that reaches it.
- Sandbox (`maxxing/agent_guard.py`, `sandbox: true` for agents created from this version, missing = false for older
  agent.json): one `--settings` merged by `spawn.settings_args` (`sandbox.enabled`, `failIfUnavailable`,
  `allowUnsandboxedCommands: false`, `filesystem.denyRead` + `permissions.deny` Read/Edit on `secret_paths()`,
  `allowWrite` agent folder + `writable`, `network.allowedDomains` = `domains`, `excludedCommands: ["maxxing:*"]` +
  `permissions.allow Bash(maxxing:*)` - a bare `"maxxing"` does not match); `--add-dir` per writable folder; mode never
  bypass (`agent_guard.mode`: bypass -> acceptEdits, Claude Code ignores the domain list in bypass). The `maxxing` CLI
  run from a sandboxed turn (found by its cgroup `maxxing-<sid8>.service`, `sandboxed_turn()`) accepts only
  `CLI_ALLOWED` (feed post|list, agents send|show|list|templates, keys get|list, status). `available()` = bwrap +
  socat + the AppArmor profile `/etc/apparmor.d/bwrap-maxxing` when `kernel.apparmor_restrict_unprivileged_userns=1`;
  unavailable -> the runner fails the turn before Claude starts (`SANDBOX_ERROR`). `maxxing agents sandbox-setup`
  (`setup()`, root, apt), `GET /api/agents/sandbox`, doctor check `agent-sandbox` (only when an enabled sandboxed
  agent exists), installer: `bubblewrap socat` in `TOOL_PKGS` + `agent_sandbox_profile`. Tests:
  `MAXXING_SANDBOX_CHECK=0`.
- Rules (`rules: [{tool: Bash|Write|Edit|WebFetch|*, match, reason}]`, max 20): `hooks.PreToolUse` = `<python> -m
  maxxing.agent_guard hook <agent path>` (`check_rules`, deny + reason), every mode.
- Claude Code format (`maxxing/agent_format.py`): `export_md` / `parse_md` / `import_md` (`GET .../export`, `POST
  /api/agents/import`, `maxxing agents export|import`; unknown fields listed in `ignored`, an import is sandboxed and
  has no trigger); `subagent: true` -> `subagents_args(topic_path)` adds `--agents <json>` to the topic's own sessions
  (prompt = role + "read <folder>/memory.md first, write there only what changes your next work, never a task log").
- Continue in Sessions (`agents.continue_in_sessions`, `POST .../runs/{sid}/continue`): a new session of the topic
  (`from_agent: {path, session}`, title kept, `source: "web"`) with the run's log copied and its Claude transcript
  copied to the topic's project folder under the same `csid` (resumed from there; no transcript -> fresh); `409
  busy` while the run is running.
- UI: Agents page apart from Sessions (`features/agents/`, `AgentsLayout` with its own list,
  `/agents/:p/:t/:a`, runs opened in place at `/agents/:p/:t/:a/runs/:sid`, links to an agent session redirected
  there); agents and their runs no longer show in the Sessions lists. Overview = one section per project, one card
  per agent (`pixels.ts`, 16x16 character from 6 parts: `color` = a UI accent, `skin`, `hair`, `hair_color`, `face`,
  `accessory`; old values mapped by `agents._OLD_AVATAR`, unknown ones = a stable pick from the name; outfit default
  = `agents.project_color` = web `projectColor`, FNV-1a % 6). Sessions sidebar: `Tree.tsx` `TopicAgents` = up to 2
  chips (face, name, state dot) under a topic row, `+N` -> `/agents?topic=<p>/<t>`, only with `agents_page` on.
- UI: Agents list (`AgentsList.tsx`) always grouped by project (workspace order); the state grouping became filter
  chips (All / waiting / to read / running / active / off with counts, empty ones hidden, not persisted); the
  `mx-agents-grouping` localStorage key is no longer read. Aside order: search, New agent, Office entry (`nav` prop,
  also on touch -> new route `/agents/office`), filter, list. Office = `AgentsOverview` with a view switch
  (`mx-agents-office-view`, `classic` by default, see Office views below). `statusOf` / `Status` moved to `parts.tsx`. i18n: removed
  `agents.side.{overview,grouping,byState,byProject}`, added `agents.side.{filter,all}`, `agents.office.*`.
- Office views: the Segmented became a menu (`ViewMenu` in `AgentsPage.tsx`: current view icon + name; radio items,
  separator, "Create my custom view" -> `draftUrl(projects/general/topics/inbox | first non-system topic,
  agents.office.customPrompt)`). `mx-agents-office-view` = `classic` | `future` | `x:<extension id>` (an old
  `game` reads as `future`); an `x:` view whose extension is gone / off / in error renders Classic without rewriting
  the key. Space (id `future`) = `OfficeFuture.tsx` (one bay per project sized by its agents, 2-5 columns, SVG pixel
  hover consoles at 4 px per pixel, 3 on phones, holo screens that never move, free console -> creation sheet on the
  bay's main topic; `mx-game-*` / `mx-future-*` keyframes in `globals.css`); what a pixel view needs is in `office.tsx` (`useRoom`, `useDesk`, `Cursor`, `hash`, `colsFor`); `pixels.avatarSvg()`.
- Extension Office views: manifest `"agents_view": true | {"name"?: str | {lang: str}, "icon"?}` + `agents-view.html`
  (`extensions._agents_view`, errors on the extension: missing file, bad value; new type `"view"` = only that,
  requires `agents_view`; `agents-view.html` in the hot-reload signature). `/api/extensions` items get
  `agents_view: {name, icon} | null`. Routes `/ext/{id}/agents-view-frame` (same document, CSP sandbox and UI kit
  as `widget-frame`, `api.extensions._frame`) and `/ext/{id}/agents-view.html` (GET/HEAD, raw). `WIDGET_BRIDGE`
  gains `maxxing.data`, `onData(fn)`, `app(path, {query})` and `navigate(route)`; web `HtmlWidget` takes `frame`,
  `maxHeight`, `className` and `host: {reads, routes, data}`: `app` answers only exact paths of `reads` (GET), else
  an error reply; `navigate` only routes whose resolved pathname is under `routes` (same origin, no `.`/`..` segment,
  no `%2e`/`%2f`/`%5c`, backslash or spaces); `data` posted on load and
  on change. The dashboard passes no host (app refused, navigate ignored). `OfficeCustom.tsx` = host with reads
  `/api/agents/layout` only (the raw `/api/agents` holds trigger prompts and key names), routes `/agents`, data = `{lang, new_agent_route, projects: [{name, emoji,
  color, agents: [{path, project, topic, name, display_name, description, enabled, model, status, status_text,
  running, waiting, unread, cost_today, last_run (text <= 300 chars), avatar, avatar_svg, route}]}]}` (pushed again
  only when its JSON changes). Docs: `13-page-extensions.md` "Office views", skill `maxxing-extension`. Tests
  `test_agents_view`, `test_editing_agents_view_html_is_seen_by_the_hot_reload`.
- Layout of the Agents page, shared by every device: `<state>/agents/layout.json` = `{projects: [name], colors:
  {project: color}, agents: {project: [agent path]}}` (`agents.load_layout` tolerant, `save_layout` strict ->
  `400 bad_layout`; colours = `AVATAR["color"]`, 500 projects / 500 agents per project max; unknown fields of the
  file kept, of the request dropped; a project / topic rename rewrites it in `agents.remap`). `GET/PUT
  /api/agents/layout`, bus `agents`. `agents.project_color` honours the picked colour (outfit of new agents, CLI
  included). Order: listed projects first then workspace order; listed agents first then topic, name. Web:
  `features/agents/layout.tsx` = `useAgentsLayout()` (sort, `colorOf`, moves; used by `AgentsList`, Classic and
  Space), `useProjectColorOf()` (creation form, `AvatarEditor`; `randomAvatar(color)` now takes a colour),
  `useReorder` (HTML5 drag and drop, off on touch; an agent drops only in its project; `DropBar` indicator),
  `ProjectMenu` (Move up / down + 6 swatches); queries `useAgentsLayoutData` / `useSaveAgentsLayout` (optimistic).
  i18n `agents.layout.*`. Fix: the creation sheet's first step now starts on the topic it was opened with (the free
  desk of a room).
- `web/src/pages/pageData.ts`: `staleTime` accepts a function (the type broke `tsc -b` after the file kind query
  change of a111).

## 2.0.0-alpha.112 - 2026-11-04

- `download.ts`: the Blob shortcut for images up to 20 MB (`fromCache`, `BLOB_MAX`) is gone: the viewer shows
  `/api/files/preview` for heavy images, so the raw URL was rarely cached and the click waited for the whole
  transfer. Every download is `?download=1` through `<a download>`. iOS app: `fetchUpTo(url, SHARE_MAX,
  SHARE_WAIT_MS = 2500)` aborts and opens the file in the app when it is not read in time (the share sheet needs a
  fresh tap anyway; before, a slow file was fetched whole, the share failed, and it was fetched a second time).

## 2.0.0-alpha.111 - 2026-11-04

- `useFileStamp`: a null stamp (missing file or failed `/api/files/stat`) is asked again by `refetchInterval`
  (2 s for 30 s, 5 s up to 2 min, 15 s up to 15 min from when the path was first seen missing, `missingSince`).
  Before, a file named in a message before it existed was only re-checked on a tool result, the end of a turn or a
  focus: one written after the last event stayed a broken image until a reload. `Thumb` shows the placeholder while
  the stamp is null (no unversioned 404 request any more) and retries a failed image 8 times (1 s to 30 s, re-asking
  the stamp; same version = `&try=N` in the URL). `fileKindQuery`: a `missing` result is stale at once and polled
  every 4 s while the viewer shows it.
- `api/files._render`: the shared render key includes the file's `st_mtime_ns`, so a file rewritten during a render
  (a video still being written) gets its own render instead of the old one's result.

## 2.0.0-alpha.110 - 2026-11-04

- `maxxing update` writes `<state>/update/in-progress.json` (rollback commit, starting branch, version, auto-save
  carried back) before the code moves and removes it when the update ends (any exit but 1, and `--rollback`). A run
  that finds it (the previous one was killed after the rebase / fast-forward) takes it over: `refs/maxxing/pre-update`
  keeps the old commit and `upgrade_notes()` / `after.json` use the old version (`_from_version()`), not this
  process's `__version__` (already the new code). The conflict `pending.json` also records `from_version` for
  `--resume`.
- `smartupdate.preflight`: `behind` = `rev-list --count HEAD..origin/<branch>` even without a merge-base (as
  `check_update`); before, a rewritten upstream history gave `up_to_date` forever (no auto update, conflicts and
  upgrade notes hidden). Without a base, upstream's changed files are diffed from `HEAD~<number of customizations>`.
- `maxxing update --rollback`: customizations of the running code missing at `refs/maxxing/pre-update` (saved after
  the update, or auto-saved on the new branch by `--branch`) are cherry-picked back onto it, then `customs.export()`
  rewrites the registry (before, the reset dropped them and the next export deleted their patch). One that does not
  apply to the old code: everything is put back as it was, exit 1.
- `maxxing update --branch X`: the local branch X is rebuilt from `origin/X` (`checkout -B`) + the customizations of
  the branch left, instead of reusing a stale local X (it resurrected customizations dropped or changed meanwhile);
  commits only on the old local X are listed and kept under `refs/maxxing/before-switch/X`. Customizations are
  replayed with `customs.pick()`: a cherry-pick that becomes empty (already merged in X) is skipped as "now included"
  instead of failing with exit 3 (`--allow-empty` only accepts originally empty commits; git < 2.45 has no
  `--empty=drop`). `customs.list_customs(head=)` lists another ref's customizations.



- Sign-in global cap (`security.begin_attempt(key, trusted)`): two slots (`_last_global` for clients with failures
  in the window, `_last_fresh` for clients with none), and `trusted` (valid `mx_device`) or a client key in `_good`
  (successful sign-in within `GOOD_KEEP_S`, memory only, `GOOD_MAX` keys) skips the cap. ~25 rotating /64s used to
  hold the single slot and lock the owner out.
- `PUT /api/auth/two-factor {"enabled": false}` now needs `password` (same "pw:" throttle as `/api/auth/password`,
  shared `_check_current`) when 2FA is on, then `twofactor.notify("off_ui")` + a feed warning. `DELETE
  /api/telegram` with 2FA on sends `notify("unlinked", wait=True)` (blocking `_send_sync`: the gateway is stopped
  right after) and a feed warning. Unlinking itself still needs no password.
- `_ffmpeg_thumb`: an image path with a `%` gets `-f image2 -pattern_type none` (image2 expanded `a%d.png` to
  `a1.png`, possibly a link out of the files root). Only then: the other demuxers refuse that option (exit 8).
- Path sites: `header_down Set-Cookie` uses `caddy.HARNESS_SET_COOKIE_RE` (spaces/tabs allowed around the name:
  browsers trim them, `mx_session =x` replaced the session). Only new site files get it: a path site added before
  keeps the old line until `maxxing infra site remove` + `add`.
- `infra db backup`: `pg_dump -Fc --dbname=dbname='<quoted>'` (a database named `-f/x` was an option, `host=...` a
  connection string); a name outside `[A-Za-z0-9_.-]` (or starting with `-`/`.`) gets a cleaned file name + sha1[:8].
- Team peers: a `waiting`/`request` link key verifies with scope `teampeer.PENDING` (only accept / refuse / bye; an
  invitation holder could say hello as a group member and post as them). A `request` from a group member keeps its
  group pair key for that group (`_key_to`), its group name and its place in `people()`. `_scopes` ignores
  `group_keys` of an accepted contact (the creator made that pair key); they stay stored for after a `bye`.
- Webhooks: every delivery verified with a secret (shopify, github, generic; not Stripe: its timestamp is signed)
  claims `_replay_key` in the new `hook_seen` table of feed.db (`feed.claim_delivery`, released when the delivery
  fails) before parsing: an ignored GitHub body replayed with another `X-GitHub-Event`, or a deleted event, no
  longer posts. Kept 30 days (`feed.RETENTION_DAYS`), generic 24 h (`GENERIC_REPLAY_S`: same alert again later).
- File site (preview) responses: `Cache-Control: private, no-cache` (was `max-age=300`: a page stayed viewable
  from the browser cache for 5 min after a sign-out).
- `normalize_lines`: the lone-surrogate pattern runs only on lines holding a `\uD8..`-`\uDF..` escape (it cost 4-6x
  the JSON parse on every line); sub-agent lines (top-level non-empty string `parent_tool_use_id`) are recognised on
  the text (`_sub_agent_line`, unsure cases still parsed) instead of being parsed then dropped.
- `tool_use` events: input text fields over `clip.INPUT_MAX` are clipped at read time too (logs older than the
  write-time clipping), and the event carries `input_lines` (real line count of each clipped top-level field; the
  runner stores it as `mx_lines` on the block). The Write card header counts the file's real lines (it said "+200"
  for any file over 200 lines).
- Files: `/preview` renders in `_thumb_pool` like `/thumb` (it took a shared `to_thread` worker for up to 30 s),
  ffmpeg / pdftoppm run under `nice -n 10`, and concurrent requests for the same (file, width bucket) share one
  render (`_render`, `_thumb_jobs`).
- Uploads: Starlette's multipart spool goes to `<state>/tmp/uploads` (`uploads.spool_dir`, patched into
  `starlette.formparsers.SpooledTemporaryFile`) instead of the system temp dir (a tmpfs here: an 800 MB upload added
  800 MB of shmem). Not via `TMPDIR` in the unit: spawn.py passes TMPDIR on to the sessions.
- Git graph (local): plain `git log -n<limit+1>` then `_topo` (equal dates now keep git's order) instead of
  `--topo-order`, which walked the whole history first (4 s at 600k commits); commits cached (`_graphs`, 32 entries)
  on repo + limit + selection + HEAD + a hash of `for-each-ref`. Commit detail: `--no-renames` first, `-M` only
  when the commit touches at most `RENAMES_MAX_FILES` (2000) files.
- Crons watcher (`api/crons.py:_watch`): no pass (glob + flock of every lock file each 2 s) while
  `bus.browser_count() == 0`; nothing server-side listens to `crons` / `health`.
- Dashboard: an extension card still computing at `SOFT_S` comes back with its last card
  (`extensions.cached_card`) plus `stale: true` and `pending: true` (the UI shows it, no skeleton, until
  `/widgets/{id}` patches the new one). `/ext/{id}/widget.html` answers HEAD; HtmlWidget's existence check uses it
  (it downloaded the whole file with `no-store` before the frame downloaded it again).
- Turn watcher: with inotify and nothing running it waits up to `WATCH_IDLE_WAKE_S` (30 s, shorter when a hand-off
  hold expires sooner) instead of a full `_scan` every second.
- `compact_log`: a read-only pass (`_log_shrinks`, stops at the first line it would change) first; a log that would
  not shrink is never copied to `.compact.tmp` and no longer needs `before + 256 MB` free (no more nightly `no_space`).


- Crons DST: `iter_runs` compares instants (`ts >= first`), not aware datetimes (same tzinfo = wall-time compare,
  so 02:45 fold=0 passed after 02:30 fold=1), and yields the fold=1 instants when the hour field is full.
  `is_due` (guarded lines, `system_clock = keep`) is now `next(iter_runs(minute - 1)) == minute`: one run in the
  repeated hour, the skipped spring time runs after the gap. `widgets.day()` ends at the next local midnight.
- Crontab block shared by state dirs: `sync_crontab` replaces only the managed lines of the current state
  (`crons._ours`: the line's `MAXXING_STATE=` prefix, none = `/var/lib/claude-maxxing`) and keeps the others, so a
  dev copy, preview server or script run with another `MAXXING_STATE` no longer wipes the live install's lines.
- `config.save_config` (so `update_config` too) writes `_chosen(cfg, DEFAULT_CONFIG, raw)`: keys already in
  config.json (new value, even if equal to the default) + values that differ from the defaults, recursively. Before,
  every save froze all merged defaults into config.json, so a changed default never reached an install that had
  saved any setting (the `*_chosen` flags of telegram/gateway.py were patches for this). Existing files keep the
  defaults they already froze.


- Search index schema 2 (`search.SCHEMA_VERSION`, checked by `_migrate` when the writer connection opens): message
  rows have an empty `title` (the session title is on its title row, `body=''`, only), `items_au` is
  `AFTER UPDATE OF title, body` (a path change re-indexes nothing). Existing indexes: one `UPDATE` of the message
  rows at the first start (~9 s for 300k rows). The query groups by `(kind, ref)` in SQL (MATERIALIZED CTE: bm25 /
  snippet cannot run inside an aggregate) and bounds the match with `rowid >= floor`, floor = the `RANK_MAX`-th
  newest match (`rowid IN (...)` runs the MATCH once per row: minutes on a prefix). `fts_query`: prefix from 3
  characters. `search(..., cancelled=)`: gives up waiting for `_rlock` and interrupts the query (progress handler);
  `/api/search` sets it when `request.is_disconnected()`. A log ending in an unterminated line is marked as seen and
  its `src` row is written only when its signature changes (no write + checkpoint per query).
- Telegram: `<state>/telegram/replies.json` (sid -> chat, thread, refs, at; written on every change of `_pending`,
  never while stopping, dropped after 24 h) lets the next process answer a turn sent before a restart
  (`Gateway._left`, matched on `last_turn.refs` in `on_turn_end`, merged into `_pending` when the session gets a
  new message). "Ask Harness" turns are tracked (`_track` + `ref`). `on_turn_end` also sets `p["ending"]` before
  cancelling the typing loop: a cancel landing inside an httpx call was sometimes swallowed, and the loop then
  dropped the ended turn's ref as not live (answer never sent). New WORDS keys; `_sender_lang(msg)` for texts sent
  before the chat is linked.


- Sessions `NewSessionColumn`: `made` ref = the session the first send created; chained later sends (text or voice)
  go to it through `send` instead of a second `create`. Its Composer now gets a `checkSent`: recent sessions of the
  path (created >= oldest entry - 600 s) whose log or queue holds an entry's `client_id` take the column
  (`outboxMove` to that session first, its own `checkSent` sorts the rest).
- Composer unmount stores the text only when `unsaved` (quotes / attachments are already stored by their effects; it
  used to overwrite another tab's draft); the debounce no longer marks the text just loaded as unsaved. A refused send
  whose composer is gone puts its attachments back in the stored draft too.
- `restoreLayout` matches the current session columns by id (solo reuses the on-screen key): a session not in the
  saved layout is added with a fresh key when its key is taken, and keeps the focus.
- Sessions: `setNewPath` to a topic that already has a `new` column closes this one and focuses that one (drafts,
  seeds and prefills are keyed `new:<path>`, two columns on one path overwrote each other).



- `components/ui/markdown.tsx`: remote images (`https?:` / `//host`) render as `RemoteImage`, a click-to-load button
  (then `referrerPolicy="no-referrer"`); same-site and relative pictures still load at once. `//host` links count as
  external (new tab, rel noopener). Key `md.loadImage` (core).
- `Markdown` is `React.memo`: a dictionary group arriving (re-renders every `useT` user) no longer re-parses and
  re-highlights every message on screen. Tasks List/Calendar group with push (was a copy per task, quadratic) and the
  List renders 200 rows per step (sentinel + IntersectionObserver, like the Files listing).
- tasks.json: `save()` re-checks the signature right before the rename (`config.write_json(before_replace=)`, run
  after the dump + fsync), so an edit landing during the write is retried, not overwritten. On save, a field
  `_norm_task` rewrote and the API did not change is written back raw (`_cache["raw"]`, `_with_raw`); id-less
  projects get a `_free_id("p_")` instead of being dropped. `_norm_task` checks `due` with `date.fromisoformat`;
  the UI `fmtDue` / quick-add `parseDue` guard impossible dates too.
- PATCH task: `prev_id` / `next_id` (sent by the Board drop) place the card server-side, renumbering the column 1..n
  when the neighbours' orders are equal or < 1e-6 apart; a status change without `order` goes on top of done /
  bottom elsewhere (the task sheet).
- Keys: PUT `create: true` (the Add dialog) -> `409 exists` instead of replacing (`vault.put(create=)`).
  `SecretInput onValueChange` switches to a masked textarea (`-webkit-text-security`) when a paste or the value
  has line breaks (an `<input>` strips them). `maxxing keys set` keeps the final newline of a multi-line value;
  `get` does not add a second one.
- Files listing DnD: `fileDrag.paths` (the selection when the dragged entry is in it, `fileDrag.selection` kept by
  Listing) + `droppedPaths()`; `EntryActions.moveTo(from[], dir)`. Drop-upload tells folders apart with
  `webkitGetAsEntry().isDirectory` (was `type || size > 0`, which dropped empty files) and toasts the skipped ones.

## 2.0.0-alpha.109 - 2026-11-04

- Today's schedule timeline: `blocks.tsx` `laneMode` picks per lane from the px gap between its two closest events
  (track width followed by a ResizeObserver): dots from 16 px, 2-3 px bars on the exact times from 5 px, else a band
  (success up to `now`, lane colour after; error/running still drawn as dots). The old dense band was a
  `repeating-linear-gradient` unrelated to the real times. `widgets.MAX_PLANNED` 48 -> 144 so every-15-min jobs
  (96 runs) send their events instead of `dense`.

## 2.0.0-alpha.108 - 2026-11-03

Release of `beta` to `main`: a103 (Team friends, edits, presence) and a104 (session list rewrite) were on `beta` only
while a105-a107 went straight to `main`. No code change in this commit: version bump and notes only. The public
CHANGELOG entry summarises a103 + a104 because installs on `stable` jump from a107 and `maxxing update` only prints
the headings above the installed version.

## 2.0.0-alpha.107 - 2026-11-03

Audit fixes (Radar, one commit each with its test): idle compaction settings read defensively; crons never save over
or drop the crontab for an unreadable `jobs.json`; tasks.json: NaN / infinite numbers -> null, too deep = corrupt,
lone surrogates replaced on read and refused (422) on write, list / object / duplicate ids get a new id; Keys: names
with a trailing newline, values with a null byte, lone surrogates refused; Import: 50 MB secret-scan budget per zip,
apply reuses the upload's scan, two applies at once serialized, encrypted / damaged zip = 400 `bad_zip`; Infra:
server name picked under the registry lock, odd ports in infra.json skipped; Dashboard: a card with a lone surrogate
fails alone. Touch targets (Tasks rows and labels, Import choices), Infra title on phones, long key names wrap.


Session list (a104 rewrite of `Tree.tsx`): back the two speed fixes of `f64f334d` that the rewrite dropped. A
filtered topic shows `SESSIONS_SHOWN_FILTERED` (30) rows then "Show more", and `SessionRows` reads `useCompact()`
once and passes `touchLayout` to each `SessionRow` (one media-query subscriber per list, not per row). Mock, 1500
sessions in 30 topics, filter matching all: 1500 -> 900 rows mounted; first keystroke CPU x4 (phone)
4.1 -> 2.7 s, next ones ~200 -> ~165 ms; clearing the filter 2.7 -> 1.6 s. Dead `halfOf` removed from
`pages/sessions/index.tsx` (`tsc -b` failed on it).

Sessions strip: up to `MAX_STACK` (3) sessions per strip column (`Col.below` chains; `store.groupAt` exported,
`normalizeCols` drops a `below` past 3 and a `wide` / `half` under a top). New `Col.half` / slot `half`: track
`max(MIN_W, 50%)`, `position: sticky` at the strip edge when it is the first / last column (`Place.stick`), the strip
gets `scroll-padding-left|right: 50%`, the other columns `minmax(max(MIN_W, 50% / k), 1fr)` with k = how many fit in
the other half (ResizeObserver), so none shows cut. Slot `trio`. Rows: `layouts.stripRows(sizes, split)` builds the
shared row template from the cuts used (pair at `rowSplit`, trio in thirds); `Place` gains `i`, `n`, `gridRow`; the
row handle (pairs only) re-applies every stack's lines live. `layoutsFor(n >= 4)` adds half + pairs / trios and
mirrors, `n >= 5` the trio grid; `fitting` keeps a half layout from 2 columns of room and the grids even when they
scroll. `unstack` = `moveBeside` the stack top (the middle of a trio left the third under it). Drop beside a stack:
`dropBeside` (store, not persisted) draws the line along every session of the strip column, not only the hovered
one.

Sessions strip speed (10 sessions open, CPU x4, mock): a Place equal to the previous one keeps its identity, so the
memoized columns (ColumnFor) no longer all re-render on every focus change (`places` depended on `focused` even out
of the tabs view); StripContext's value only changes with the number of columns (template / places read through
refs); column and row resize apply once per animation frame; an empty Textarea sets its height without measuring
(`height: auto` + `scrollHeight` forced a page layout per open composer when a layout change moved `maxRows`).
Drag over the strip: long tasks -50 %; layout switch: -15 %, p95 frame 50 -> 33 ms; row resize worst frame
250 -> 140 ms (what is left there is paint: every open session really changes size).

Column width: `MAX_W` 1400 -> 2000, and a column resize stops at what the strip can show (others at `MIN_W`), so
the handle never moves for nothing. A column widened by hand past 900 px sets `--mx-read: none` on its section: the
thread, composer, tasks, aside and error box use `max-w-(--mx-read,860px)`. Short stacked sessions
(`useSlimHeader`: stacked and under `SLIM_BELOW` = 560 px, ResizeObserver on the section) get a one-line header:
picture-in-picture, the topic / cost line, and plan / Telegram unless on are hidden; plan and Telegram are checkbox
items in the … menu.

Half column: no longer pinned (`Place.stick`, sticky position, scroll padding, snap-mandatory and the settle
listener are gone): FEU wants the other sessions never to pass under it, so it scrolls with the strip like any column.
It keeps half the visible width and its neighbours share the other half exactly. While a half is shown, `template`
ignores `widths` (a hand width collapsed it to `MIN_W` against neighbours of `max(MIN_W, 50% / k)`), resize handles
are hidden and `startColResize` returns.

Stacked composers: only a stack of three folds the unfocused composers into the "Write…" bar (`StackedComposer`
`stacked = place.n >= 3`); two stacked sessions both keep their composer (still `maxRows` 4).

Sessions strip: no scroll snapping any more (`snap-x snap-proximity` on the strip, `snap-start` on the columns, the
wheel handler's snap toggling, `glideToColumn` and `columnStop` removed): the strip stays where it is scrolled to.

Composer drafts survive a reload: the text is also written on `pagehide` / tab hidden when the 250 ms debounce has
not run yet (only if this composer has unsaved text, so an idle tab does not overwrite another tab's draft); uploaded
attachments are stored with the draft (`mx-draft:<k>:atts`, `loadAtts` / `saveAtts`). Outbox
(`mx-draft:<k>:out`, `outboxAdd` / `outboxDone` / `outboxMove` / `leftOutbox` in store.ts): each send is written
before the request and removed once it is answered (a failure: 1.5 s later, only if the page is still here, since a
reload cuts the request and that is not a refusal; a leftover already back in the draft is not added twice). On mount the composer takes what a previous load left; the session column's `checkSent` loads
the log and drops what the server got (a user event with the same text since the send, or a queue item it starts
with), the rest comes back in the box with a toast (`sessions.composer.sendInterrupted`). `null` = could not tell:
the entries stay for the next load. `lib/busy.ts`: sends and uploads in progress hold the automatic switch to a new
build (pwa `announceUpdate` waits for `onIdle`).

## 2.0.0-alpha.106 - 2026-10-31

Audit fixes. `resume.threshold()` and `candidate()` read `smart_resume_tokens`, `context_tokens`, `base_tokens`, `finished_at`,
`cache_at`, `idle_compact_after_s` defensively (TypeError / ValueError / OverflowError -> off). `mcp_auto`: RecursionError caught where the
configs are parsed, the session file is written ASCII-only and its `.tmp` removed on failure, the left-out list of the
hint is capped (40 servers, 120 chars each, "and N more"). Name patterns are `lru_cache`d and `.claude.json` is
parsed again only when `(path, mtime_ns, size, inode)` changes (`mcp_auto._read_cfg`, which raises like a plain read
so an unreadable config still means "load everything").

## 2.0.0-alpha.105 - 2026-10-31

Smart resume (`sessions/resume.py`, config `smart_resume_tokens`, default 100 000, 0 = off; Settings -> Claude, GET
status / PUT settings). A user message to a session whose cache expired (`idle_compact_after_s`) with at least that
context, or after a pause of 5 min+ with twice that, gets a summary turn first whose prompt (`resume.summary_prompt`)
carries the message (<= 6000 chars): the plain 15-line summary plus "For the next message", the details it relies
on kept exact. Note "Back after ...: Harness summarized the session (...) for your message". Otherwise
`_idle_compact` (plain summary) as before. Measured on 30 real returns (blind judge vs the turn done with the full
history): nothing missing 9 vs 2 for the plain summary, important detail missing 1 vs 2; tokens of the resumed turn
-38 to -45 % at 100-200k, -67 % from 200k, -11 % at 60-100k. No classifier call any more (the first version's haiku
call never worked outside the tests: `communicate(input, timeout=0.2)` retried with input raised ValueError).

MCP servers loaded per turn (config `mcp_auto`, default **false**; Settings -> MCP switch, `PUT /api/mcp/auto`).
New `maxxing/mcp_auto.py` (stdlib only). When on, `mcp_auto.plan()` (runner `turn()`) gives the turn
`--strict-mcp-config --mcp-config <state>/mcp-auto/sessions/<sid>.json` (0600, folder 0700, rewritten only when its
content changes, deleted by `store.remove`) with the full configs of: user-scope servers used by the topic
(`<state>/mcp-auto/topics/<sha1(path)[:20]>.json` `{path, used:{server in tool form: ts}}`, 60 days, written at turn
end from every `mcp__<server>__*` tool_use, subagents included), named in the message (whole name, or a 4+ letter word
of it no other server has), or in meta `mcp_loaded`; plus every local-scope server of the cwd and the approved
`.mcp.json` servers of the cwd and its parents (Claude Code reads parents too; verified). `disabledMcpServers` /
`disabledMcpjsonServers` of the cwd are respected; harness-pc is left to pcbridge's own `--mcp-config` (two
`--mcp-config` flags work together, verified). Strict also drops claude.ai connectors: if one is needed, no flag at
all (everything loads). Connector names: `<state>/mcp-auto/connectors.json`, from the init event of unrestricted
turns (`source: "claudeai"`) and from `mcp.check()` (`connectors_of_list`, lines with spaces that `parse_list`
skips). Unreadable .claude.json = no restriction. Servers left out go into the system prompt (hint with kind + URL
host / program, never secrets) with `maxxing mcp load "<name>"`: `spawn.agents_args(cfg, extra)` now joins the
foreground-agents text and that hint in ONE `--append-system-prompt` (Claude Code keeps only the last of several:
verified). Turns get `MAXXING_SESSION=<sid>`; `maxxing mcp load NAME [--session ID]` resolves the name (any case,
with/without "claude.ai ", tool form) and appends it to meta `mcp_loaded` (50 max). `runner._mcp_after()`: if
`mcp_loaded` got a server the turn did not have (strict turns only, not after an error / stop / plan turn), queues
first `{source:"system", kind:"user", mcp_continue:n, text:"[Harness: the MCP server X is now loaded...]"}`, at most
`CONTINUE_MAX` = 2 in a row. Measured (haiku, /tmp, this box's servers): 24.2k -> 18.5k tokens per call with
nothing loaded; Facebook-ads alone ~3.4k. Note: a change of the loaded set changes the tool list, so the next call
after it re-creates the prompt cache once. Tests: `tests/test_mcp_auto.py` (fake claude: MCPUSE:, MCPLOAD, MCPINIT).

Sessions page: dropping a column on the upper third of a session alone in its column stacks it above (new store
action `stackAbove(key, over)`: the dragged session takes the target's strip column, its `wide` and its saved width,
the target goes `below`); same dashed zone as the lower third, drawn at the top.

Claude plans renamed by Anthropic on 2026-10-31 (Max 5x -> **Max**, Max 20x -> **Ultra**; verified Ultra accounts no
longer have the 5-hour limit). `claude_auth.plan_name()` reads the plan from the `claude login` credentials
(subscriptionType + rateLimitTier `..._20x` = Ultra); `/api/usage` gives it as `plan` (None with a setup-token or an API
key). Sidebar bars, Settings -> Stats and the dashboard widget show the plan, and with Ultra and no 5-hour window
they say "no 5-hour limit" instead of a missing bar (accounts not verified yet keep their 5-hour bar: it comes from
Claude Code). Texts "Pro or Max" -> "Pro, Max or Ultra" (README, docs, sign-in).

Server speed fundamentals (measured on a box with 184 sessions: the server used ~5 % of a core with 3 sessions
running, mostly polling).
- `config.load_secrets()` is cached like `load_config()` (key: path, inode, mtime_ns, size, ctime_ns; pickled, a
  fresh copy per call); `set_secrets` and `write_json` of secrets.json drop it. `cookie_valid` no longer parses
  secrets.json on every request (66 -> ~25 µs). `config.workspace()` / `files_root()` / `claude_dir()` read one
  setting from the cached merged config (`_setting`) instead of unpickling the whole config.
- `workspace.py`: CLAUDE.md descriptions, `.maxxing.json` and `projects/.order.json` are cached per file on their stat
  (`_cached`; a file changed less than `RACY_S` = 2 s ago is read again; the writes here call `_forget`);
  `_folder_meta` returns a copy. `tree()` / `list_topics()` read the workspace root once (`_one_root`).
- `store.list_ids()` keeps the ids in memory and lists the folder again only when its mtime changed (or changed less
  than 1 s ago): 1.1-1.5 ms -> ~10 µs with 652 files. `store.prune_locks()` removes the `.lock` / `.run` of sessions
  that are gone or idle for an hour, under their lock; `_flock` and `hold_run_lock` check after locking that the
  file is still the one at the path (fstat vs stat) and start again on a new one. `runner_alive` no longer creates
  a missing `.run` (no file = nobody holds it).
- New `sessions/wake.py`: one `watchfiles` RustNotify thread on the sessions folder (not recursive; debounce 100 ms,
  step 50 ms) wakes the per-session SSE streams (`<id>.log` / `<id>.json`) and the turn-end watcher (`<id>.json`)
  through asyncio events taken before looking (`mark` then `wait`: nothing missed in between). With it the streams
  look at least every 2 s while running (`WAKE_RUNNING_S`) / 1 s idle, the watcher every 2 s while running /
  `interval` idle; without it (no inotify, `MAXXING_INOTIFY=0`, another loop) the old polling (0.1 / 0.25 / 1 s).
  `watchfiles` is now a declared dependency (it came with `uvicorn[standard]`).
- `session-watcher.json`: written after the first pass, at once after a report, and at most every 5 s after passes
  that saw a change (never when nothing changed; was every 5 s with indent + fsync); compact JSON, no fsync.
- Feed watcher: `feed.watch_id()` reads nothing while feed.db and its WAL are unchanged and keeps one connection
  (`check_same_thread=False`, under a lock; reopened when feed.db is replaced) instead of a new one every 3 s.
- Logs: `clip.clip_event` drops `thinking.signature` and `redacted_thinking.data` (~16 % of the logs measured);
  `clip.worth_clipping` also lets short lines carrying them through `clip_line` / `compact_log`. New
  `sessions/maintenance.py`: every night at 04:30 (server time) compacts the logs written since the previous pass
  (`<state>/sessions-maintenance.json {at, retry}`; running ones retried the next night), then `prune_locks()`.
  Disabled in tests with `MAXXING_SESSION_MAINTENANCE=0`. The first pass after the update compacts every log once.
- `search.reclaim()`: after a files walk, at most once a day, VACUUM when more than 25 % of search.db is free pages
  (and it is at least 4 MB).

Video player (branch `opt/video`). Public text for the next CHANGELOG.md entry: videos play sharp (the original
whenever the browser can decode it), keep playing through a server restart or a network drop, remember volume, speed
and where you stopped, no longer jump while loading; GIFs move in conversations and inline audio keeps playing when
you scroll away.

- `GET /api/files/video/stream` sets the atime only (`os.utime(ns=(now, st_mtime_ns))`, `stat_result` passed to
  `FileResponse`): touching the mtime changed the ETag / Last-Modified on every request, so a Range request with
  `If-Range` got a 200 (whole file) and playback restarted. `videos._trim_cache` sorts on atime and skips copies
  played in the last 30 min (`COPY_KEEP_S`; the cache may stay over `VIDEO_CACHE_MAX` meanwhile).
- `videos.auto_quality`: 1080 above 1080p (was 720), 720 for a heavy original ≤ 1080p. Encoder `-preset faster -crf
  20`, maxrate 8M / 4M / 1500k, bufsize 2x (`encode_args`). Copy file names gain `-r2` (`COPY_REV`): the blurry
  crf 23 copies are never served again and age out of the cache.
- `videos.probe` reads every stream (no `-select_streams v:0`): new `has_audio`, `rotation` (side data or `rotate`
  tag). The in-memory probe cache is per process, so no stale entry without the new keys survives a restart.
- `GET /api/files/thumb` gains `anim=1`: a `.gif` ≤ 8 MB (`GIF_ANIM_MAX`) is served as it is.
- Web, `features/files/`: `videoQuality.ts` (`canDecode` = `canPlayType` with a `codecs=` string per ffprobe codec;
  Auto targets `info.auto` only when `needCopy`: original undecodable / format error, or rough), `MediaPlayer.tsx`
  (frozen source + "File changed · Reload", lost-connection retries 1 / 3 / 6 s then a 5 s probe, error triage through
  a `Range: bytes=0-0` fetch, box sized with `cqw`/`cqh` from the info then `videoWidth`, throttled seek on drag, touch
  first tap, iPhone `webkit*fullscreen` events, GIF-like clips), `mediaMemory.ts` (`mx-media-prefs`, `mx-media-pos`:
  LRU 100, 1 s debounced writes, flushed on `pagehide`), `sharedAudio.ts` (inline chat audio owns an `Audio()` outside
  React, one per path, dropped when paused or ended with no player mounted). `MediaView` is a size container
  (`container-type: size`, `min-h-40`); `MediaSkeleton` replaces `CodeSkeleton` for media in the viewer. `Thumb`
  takes `anim`; chat thumbnails sit in a fixed `aspect-[4/3]` box.

Downloads:
- `downloads.content_disposition(name)` names every download (`/api/files/raw?download=1`, `/api/team-peer/files/{fid}`,
  `/api/pc/download/{target}`): `attachment; filename="<ASCII>"; filename*=UTF-8''<name>`. Starlette's `filename=`
  raised `UnicodeEncodeError` (500) on a name that is not UTF-8 on disk (lone surrogates) and sent no plain
  `filename=`. Such a name is now read as Latin-1 (`caf\xe9` -> `café`); slashes, control and bidi characters are
  replaced or dropped (a peer's file name is untrusted), names are cut at 200 characters keeping the extension.
- `GET /api/files/zip?path=`: a folder as a zip, streamed (`downloads.zip_plan` walks it first in a worker thread and
  refuses with `413 too_large` past `ZIP_MAX_BYTES` 2 GB uncompressed / `ZIP_MAX_FILES` 100,000, before any byte;
  `downloads.zip_stream` is a sync iterator over a `zipfile.ZipFile` writing into an unseekable sink, so entries use
  data descriptors and ZIP64 when needed). Symlinked folders are never followed; a symlinked file only when it resolves
  to a regular file inside the files root; FIFOs, sockets and devices are skipped. A file that grows meanwhile is cut
  at its planned size; one that became unreadable is left out.
- `GET /api/files/zip?check=1` answers `{count, size}` or the same `413` without zipping: the UI asks it first, since
  a link download the server refuses fails without a reason.
- UI (`features/files/download.ts`): every download is the browser's own download of `?download=1` (streamed to disk,
  progress, any size); images and PDFs are no longer read into a Blob. Only shortcut left: an image with a version
  (`v`, given or `knownFileStamp`) of at most 20 MB (size given, else Content-Length / bytes read) is fetched from
  the versioned URL the viewer shows and saved from a Blob. `downloadProps` lets a plain click follow the link unless
  that shortcut or the iOS path applies, and then prevents only the native event (a Radix menu item checks the React
  event's `defaultPrevented` before closing). Callers pass `{version, size}` (listing entry, viewer stamp / parent
  listing, read size).
- iOS home-screen app (`inIosApp()` = `isIOS() && isStandalone()`): Download -> `navigator.share({files})` up to
  50 MB when `canShare` accepts it; else (or when the share is refused) `location.assign` of the inline raw URL in the
  app. "Open raw" links (`openRawProps`) drop `target=_blank` there: Safari has no session cookie (401).
- File viewer: Download no longer hidden on phones; below `sm` Download (or Download as zip), Open in Files and Parent
  folder sit in a "More actions" menu. Folders: Download as zip in the viewer header and in the listing row menu
  (`useDownloadZip`).
- PC agent download: `pcbridge.agent_binary` -> `agent_file` (a path; the cache is hashed in chunks) and `personalised`
  returns `(name, agent path, trailer)`; `/api/pc/download/{target}` streams the file then the trailer instead of
  holding a personalised copy of the binary in memory per request.

Drag content between sessions (`web/src/pages/sessions/contentDrag.ts`):
- One delegated `dragstart` / `dragend` on each thread scroller (`Thread.tsx`): the target is a message grip
  (`[data-mx-drag]`, its text registered in a WeakMap by `gripRef`, no listener per row), a file (`[data-mx-file]` /
  `#mx-file=` link, same lookup as `FileMenu`) or the selection (dragstart on a text node). File elements of the
  thread carry `draggable`; grips show only on a fine pointer when the strip shows several sessions
  (`data-multi` + `group/strip` on the strip, `index.tsx`).
- Data: `application/x-mx-content` = `{v: 1, kind: 'text' | 'file', text | path, from: <session id>, nonce}` and a
  `text/plain` fallback (a selection keeps the browser's `text/html`). The drag state (`useContentDrag`: `drag.from`,
  `over`) is a tiny zustand store set one frame after dragstart (like the column grip); only `ContentDropOverlay`
  (Column.tsx) subscribes to it.
- Drop (`SessionColumn` / `NewSessionColumn` body, before the OS-file handling): taken only while a drag started in
  this tab is on and its `nonce` equals the per-tab random one (module memory); otherwise not handled, the browser
  default stays (plain text into a field). Same session: `dropEffect = 'none'`. Text: control / bidi characters out,
  20 000 characters at most; path: a string, absolute, `.` / `..` / `//` resolved, 4096 at most, never fetched, only
  inserted as `fileQuote(path)`. A thread picture also carries `Files`: `isFileDrag` ignores drags with the content type.
- i18n: new lazy group `drag` (`drag.*`), loaded on the first dragstart.

Several files at once (Files page and the folder grid of the file viewer):
- `POST /api/files/zip {paths}` (1-1000): every path through `resolve()` (the files guard), must exist; duplicates
  and entries inside another selected folder dropped; `downloads.zip_plan_many(items, root)` plans them side by side
  at the top of the zip (`zip_plan` is now its one-folder case), names made unique (` (2)`, casefolded), the
  2 GB / 100,000 caps on the whole set. Answers `{count, size, name, token, expires_in}`; `GET /api/files/zip?token=`
  streams it (a link download cannot POST). Tokens: in memory (`_zip_tokens`, at most 200, 120 s), bound to a
  sha256 of the session cookie, the paths resolved and planned again at download time. CSRF as every POST
  (`X-Maxxing`).
- UI `features/files/selection.tsx`: `useEntrySelection({entries, onOpen, root})` keeps the selection (a `Set` of
  paths, pruned when entries leave the list) and returns delegated handlers (`bind`) for the container: items only
  carry `data-row` + `data-path` + `.mx-tile` (no iOS callout, no text selection). Long press = one 450 ms timer for
  the whole container (cancelled past 8 px, on pointercancel / dragstart); the click after it is swallowed; Android's
  touch `contextmenu` counts as the long press. Escape is caught on `window` in capture (before the viewer's Radix
  dialog) while something is selected, focus inside the view, no field focused. `EntriesMenu` (point-anchored
  DropdownMenu), `SelectionBar`, `SelectCheck` (empty circles come from `group/sel` + `data-selecting` on the
  container: entering selection mode re-renders no item), `useRemoveEntries` (one confirm, deletes one by one),
  `useCopyPaths`. `download.ts`: `downloadZipMany`, `useDownloadEntries`.
- Files page `Listing`: `Row` / `GridItem` memoized, no own click handler; `EntryActions.removeMany`. Entries are
  draggable only with `(hover: hover) and (pointer: fine)` (a long press on iOS started a drag). `FolderView`
  (viewer): same model, rename (NameDialog of the Files page) and delete there too, `onOpenInFiles`; tiles get
  `.mx-cv-tile` (content-visibility) past 300 entries. Texts: `files.sel.*` (group `files`).

Video qualities of vertical videos: "1080p" is the short side (`videos.short_side`, `shortSide` in videoQuality.ts).
A 1080x1920 video showed "1920p" and its "1080p" copy was 608x1080 (scaled by height). Copies now scale the short
side (`scale='if(gt(iw,ih),-2,q)':'if(gt(iw,ih),q,-2)'`, after ffmpeg's autorotation); vertical copies get new names
(`-r2-v`), so the old blurry ones are never served (they leave with the cache trim). `/video/stream` answers 422
instead of 500 when the source can no longer be read.

Video Auto quality follows the connection (`web/src/features/files/netSpeed.ts`). While a video plays, the player
measures the download speed every 2 s (media seconds gained x the source's bitrate; a sample counts as the real speed
when the buffer runs low or grows faster than playback, else it is only a floor) and keeps it 30 min per connection
type in `mx-net-speed`. `autoPick` plays the sharpest version under 80 % of that speed (copy bitrates from
`/video/info`, typical ones until a copy exists) and under the stall ceiling; with nothing known it plays the original.
On a slow link the next video starts straight on the light copy; Data Saver caps at 1.5 Mbit/s; the poster is 640 px
under 3 Mbit/s. Fixes: the copy name follows the displayed orientation (rotation 90/270 = `-v`), copy URLs carry the
copy revision (`r=`, no stale browser cache), "Preparing" no longer spins forever (asks again when the copy went
missing, retries a failed one after 15 s), a seek or a pause is no longer counted as a stall (4 s after a seek), Auto
never switches source in the middle of smooth playback (only on a stall, a pause or the end), an .avi/.mkv the browser
cannot decode falls back on a copy, a quality picked after an error is asked again.

Sidebar: the **Extensions** entry no longer shows the count of enabled page extensions that are not pinned. It read
like a notification, and the stock "Your pages" (workspace template) made it 1 on every install.

Session tree: folding works while a filter is on. A search or the running / unread filter passes `forceOpen` to every
project and topic, which ignored their fold button (the chevron showed, the click did nothing). Now `forceOpen` only
unfolds by default: a click folds the row in `useSessionsUI.narrowFolded` (not persisted, emptied when the search or
the filter changes, `useFoldToggle` in Tree.tsx); without a filter, folding stays in `expanded` as before.

Pasted data becomes an attachment (`web/src/pages/sessions/pasteAsFile.ts`, `Composer.onPaste`):
- `pastedFile(text)` -> `{ext, type}` or null (text). Trimmed text under 400 chars: always text. Valid JSON
  (`[`/`{` ... `]`/`}` + `JSON.parse`) -> `.json`; 3+ lines all JSON -> `.jsonl`; `<...>` on 3+ lines -> `.html`
  (doctype/html/head/body) or `.xml`; 4+ lines with the same 2+ count of tab / `,` / `;` on 90 % of them -> `.tsv` /
  `.csv`. From 2000 chars: 60 % of 10+ lines starting with a date or time -> `.log`; a 200+ char run without space
  or more than 3 % code signs (`{}[]<>=/\$_`|&*#@^~+%`) -> `.txt`. From 20,000 chars anything -> `.txt`. Prose has
  ~0 % code signs, so a long prompt stays text.
- The file (`pasted-YYYY-MM-DD-HHMMSS.ext`, local time) goes through `addFiles` (now returns the local ids). Toast
  with **Paste as text**: removes that attachment and inserts the text at the selection saved at paste time.
  Ctrl/⌘+Shift+V within 1 s before the paste skips the check. i18n: new lazy group `paste` (`paste.*`).

Installer speed and re-runs (`install.sh`):
- Background jobs: `bg_start NAME CMD...` runs CMD in a `set -e` subshell, output in `$WORK/bg-NAME.log` (copied to
  `<state>/logs/install-failed-*` with the other logs); `bg_wait NAME` returns its exit code and prints the log tail
  on failure. PIDs in `BG_PID` (assoc array). `on_exit` waits for a running `apt` job (never cuts dpkg; `$WORK` is
  its TMPDIR) and kills the others with their children (`kill_tree`, pgrep -P).
- Packages: `BASE_PKGS` still in the foreground (git, curl, python3... needed next); `TOOL_PKGS SEC_PKGS
  BROWSER_PKGS` (+ ufw) in ONE background apt job (`apt_tools`: `apt-get update` there when the foreground did none,
  `pkg_known` filter, `apt_install` = no-recommends then with). `apt_wait` (in `setup_caddy`, `secure_server`,
  `install_tools_now`) waits, dies on failure like before, reports skipped names / count / missing ffmpeg. Only one
  apt/dpkg at a time (the DPkg lock timeout would serialize a missed call anyway). `ensure_swap` moved first.
- Downloads: `prefetch` starts the Claude Code and (when not the pinned one) uv downloads after the clone;
  `python_sync` (the `uv sync`) starts in the background right after uv and runs while Claude Code installs; the
  steps are now ... uv, Claude Code, Python environment, init. Overlap: the apt job (~1-2 min on a fresh VPS) with
  clone + uv + Claude Code + uv sync + init; uv sync (~20-60 s) with the Claude Code install.
- Download cache: `fetch_verified` keeps verified files in `CACHE_DIR` (`/var/cache/harness-maxxing`, 700, refused
  if a link or not ours) named by sha256, re-checked on each use, hard-linked (or copied) to DEST; a `.part` left by
  a cut transfer is resumed (`curl -C -`, from scratch if the server refuses). `cache_clear` (end of a successful
  install) deletes only `<sha256>` / `<sha256>.part` files, then the folder if empty. `CACHE_DIR` is validated like
  the other paths (`safe_path`, `not_system_dir`). uv's own cache (`~/.cache/uv`) and the managed Python already
  survived a failed run; Node.js / Chromium are `maxxing deps update`'s (not covered).
- Clone: the keyless public clone is partial (`--filter=blob:none`, 42 -> 11 MB today). Every git command of
  `maxxing update` / customs works on it (blobs fetched on demand, batched by checkout; tested: fetch, merge
  --ff-only, show, format-patch, rev-list --cherry-pick, cherry-pick). Lazy fetches go to the public origin without
  a token, so a `GH_TOKEN` clone (private fork) stays full. Offline, showing a file of a version never checked out
  fails (needs the network, like the fetch before it).
- The documented one-liner is `curl --proto '=https' --tlsv1.2 -fsSL https://get.harness-maxxing.com | bash`
  (README, docs/user, skill maxxing-backup, install.sh help). The site (harness-maxxing-cloud) still shows the old one.

## 2.0.0-alpha.104 - 2026-10-28

Session list (`feat/session-list`, web only):
- `pages/sessions/Tree.tsx`: `ListHeader` (filter + chips `show: null|running|unread`, touch New session button)
  and `ViewMenu` replace the bottom bar (`ListBySwitch`, `ModeButton`, `FlatSortButtons`, `ListOptions`, fold
  button). Touch targets stay at 40 px (FEU's a103 fix of the old footer carried to the new header: clear button,
  drill back). Topic counters: one `ml-auto` (two pushed them apart); row actions `HOVER_ACTION` / `HOVER_HIDE`
  take no width until hover.
- `Column.tsx`: `WhereBadge` (exported; `generic` = the word itself, no name or folder) under the session title;
  texts `where.*` in their own i18n group `where` (`i18n/groups.ts`), off the first load. The page subtitle
  (`sessions.description`) marks the badge words with `[brackets]` (`SubtitleWithBadges` in `index.tsx`).
- `components/shell/Sidebar.tsx`: `ResizeEdge`; `sidebarWidth` in `mx-ui` (`SIDEBAR_W` 220-440, default 264
  instead of 232; null = default).
- First-load budget (fr): the dead `soon.*` texts were removed to make room.

## 2.0.0-alpha.103 - 2026-10-26

Team, three commits (`feat/team-ui`). Mixing versions only loses the new features: an older server answers the new
event kinds with 400 (`unknown_event`, dropped from the outbox), or 403 when they come with a group key (retried up
to `OUTBOX_DAYS`, then dropped). typing / read / presence are signals, never queued.

Server:
- New routes (API.md): `POST /api/team/presence`, `/chats/{cid}/typing`, `/chats/{cid}/messages/{mid}/edit|delete`,
  `/chats/{cid}/group` (`name?, emoji?, add?, remove?`, creator only), `/chats/{cid}/leave`, `/chats/{cid}/mute`;
  `messages` takes `reply_to`.
- New inbox events: `typing` (signal: never queued, `signal_all` pool of 4 batches, 4 s timeout, one timer per person
  `_typing_gen`), `read` (Seen: only forward, never in the future), `edit`, `delete` (author only; a taken id or
  someone else's message changes nothing), `leave` (final), `presence` (contacts only, `last_seen`; sent at most every
  120 s), `profile` (on `PUT /api/settings/profile` when `team_page`: `teampeer.share_profile()`). Group keys accept
  `typing|read|edit|delete|leave` of their group too.
- Chat fields: `admin` (creator), `muted`, `left: "self"|"removed"`, `seen {person: at}`; message fields `reply_to`,
  `edited`, `deleted`, `kind: info` (local line, `info: joined|removed|left`, never sent). `_send_group(chat, peers,
  new=, removed=)` sends pair keys only for pairs with someone new; removed members get the roster without them.
- Hardening (review): `_finite` on every number from a peer (a NaN `at` broke `GET /api/team`); a roster stores
  nothing unless we are in it, in one write (`add_group_peers`, at most 500 group-only peers, a known person's name
  is never renamed by a group); pair keys must be 32 bytes (`_key_ok`); malformed event = 400; outbox: 400 / 413
  dropped, 403 / 404 retried (roster / message order); removed members' keys dropped; summaries render without
  remote images.

Web:
- `features/team/`: `Side.tsx` (Chats / Friends tabs), `Friends.tsx`, `people.tsx` (avatars, presence, typing),
  `Live.tsx` (presence ping every 150 s while visible, notifications through `notifyTeam` in `mx-ui`, Settings ->
  Notifications), `SendTo.tsx` (session message menu -> "Send to": DM created on first send, text only, ≤ 8000);
  `Connect.tsx` removed. Panel width `mx-team-width` (`PANEL_W`). Bus `team_live` = `['team','state']`.
- Session message menu (`pages/sessions/Items.tsx` `useMessageMenu`): `SendToSub` sub-menu, `SendToDialog` opened
  after the menu closes. Key `sessions.msg.sendTo` in the core dictionary, the rest under `team.*`.
- Tests: `test_team.py`, `test_teampeer.py` (new events, hardening).

## 2.0.0-alpha.102 - 2026-10-26

Integration of #23, the port of the pre-squash `fix/telegram-all` (a76-a79 there, never merged). `web/dist`
rebuilt here.

Formatting of every outgoing message kind:
- `crons._run_claude` returns the whole answer; `run_job` stores `output_tail = fmt.head(answer, OUTPUT_TAIL)` for
  Claude jobs (the start, cut on a line/word) and passes the answer to `_notify(job, run, answer)`. Shell jobs keep
  their tail; reports and the feed body use `fmt.tail` (cut on a line). `_notify` calls
  `gateway.notify_cron_report(header, body, markdown, loud=not ok)` (falls back to `notify_cron(text)` if absent).
- `format.py`: tables -> `_table_lines` (bullet per row, `<i>header</i>: value`, `\|` kept); `render()` packs the lines
  of an oversized text/table block into the current message (separator `\n`) instead of starting a new one;
  new `head`, `tail`, `preview`, `code`.
- `feed_message` renders the body (`fmt.render(fmt.head(body, 700))`); `finished_message` uses `fmt.preview`.
- `render_status` drops whole lines instead of slicing at 4000 (the slice could remove `</blockquote>`);
  `_progress` and `_edit` retry a refused HTML edit as plain text, `_edit` logs instead of `pass`.
- Tests `test_telegram_format.py`; `test_blocks` expects the table as a list. Real-chat check script (not shipped):
  every kind sent to a thread, entities checked.

Reliability:
- Turn refs: `service.send_message(..., ref=)` -> runner `turn_refs` -> `last_turn` (passed to session callbacks, not
  in the public API); steer merges refs; `service.live_refs(sid)`. `on_turn_end` answers only turns carrying a pending
  ref; compact / handoff / seed turns are never answered nor mirrored. The typing loop drops refs no longer live (5 s
  grace); `/stop` clears them.
- `_thread_gone` no longer matches "closed": TOPIC_CLOSED -> `reopenForumTopic` + resend (`send_html`, `_send_sync`,
  twofactor `_send`). `reopen_thread` takes `_sync_lock` and re-checks the mapping (`new_session` sends its quote after
  releasing the lock).
- `gateway.system_alert(text, loud)` -> "Alerts", setting `notify_system` (default true; config, API, backup keys; no
  UI toggle yet). Used by claude_update (when `feed.system` did not dedupe; it now returns the event), smartupdate,
  cmd_deps, backup, `cmd_core.notify_update` / `_notify`, `deps.notify_vulnerable` (were `notify_cron`).
- "Where?" entries persisted in `state/telegram/new.json` (timers re-armed at start; an entry being created at a stop
  gets a "send again" notice); albums use the in-flight list; `_start_new` catches errors and keeps the messages; a
  "starting" marker appends messages typed meanwhile.
- `_is_service` ignores service messages (except `forum_topic_created`). Topics turned off only on explicit refusals
  (not a forum / not enough rights / topics disabled), never on 429/5xx/network; a 429 on create/rename ends the sync
  pass. `call_sync(max_wait=)` (60 s for notifications); `_send_sync` retries each part; `send_html` waits out
  429/5xx/network twice.
- `crons.run_job`: `_notify` after the flock is released. `service.session_exists`: the sync keeps the thread of a
  session whose file exists but cannot be read. Gateway re-syncs on "feed" changes when the Notifications thread is missing.
- Tests `test_telegram_reliability.py` (25); `FakeService` models refs/queue/steer.

Setup and linking:
- State: `poll_error` (+ `poll_error_code`: `conflict`, `unauthorized`…) set only by the poller (`_set_poll_error`), `sync_error`
  set only by the sync, `topics_notice` (threads off: not an error, doctor OK with a note), heartbeat `last_poll_ok` +
  `poller_pid` (≤ every 30 s). `last_error` kept for old readers (poll error first, else sync error; old state files read).
- Linking: updates dated before the link was created are skipped; a pending link (or one expired < 24 h) answers a
  wrong/expired/missing code with `LINK_WORDS` (en/fr) and never adds the chat to `refused`; a new link clears `refused`.
- Token save: `getWebhookInfo` failure -> `webhook_check_failed`; webhook -> `webhook_set`; 2 s `getUpdates` probe -> 409
  `conflict` (our own poller paused during the probe); `unreachable`, `bad_token`.
- API: new `POST /api/telegram/webhook/remove {token?}`; `GET /api/telegram` + `link, poll_error, poll_error_code,
  sync_error, topics_notice, last_poll_ok, last_poll_age`; `POST /api/telegram/link` + `expires_at, expires_in`;
  `GET /api/telegram/link` + `pending`; `POST /api/telegram/sync` + `notice`; `POST /api/telegram/test` ->
  `{ok, sent, poller, webhook, problems}`.
- CLI/doctor read the heartbeat from the state file: warn when the poller is not running, last poll > 5 min, token
  rejected or sync failed. UI: setup done = chat linked; Change bot / Link another chat / Disconnect at every stage.
  Showcase `telegram-setup`. Tests `test_telegram_connect.py`.

Incoming side and polish:
- `_with_context(msg, text)` (in `_dispatch` / `_flush_group`): reply (`quote.text` or 500 chars of the replied message;
  the implicit reply to a forum thread's first message is ignored), forward origin, `text_link`/`text_mention`
  expanded (UTF-16 offsets).
- `allowed_updates` + `edited_message` -> `_on_edited` (one silent notice per message, owner only).
- Long pastes: a text ≥ 3500 chars waits 1.5 s and merges the next text parts of the same chat/thread (`_pastes`, in the
  in-flight list). Albums go through the session lane; the wait restarts per item, cap `MEDIA_GROUP_MAX` = 6 s.
- `_is_voice` = `voice` / `video_note` only (audio = document). Media messages are never parsed as commands.
  `resolve_model()` (id, label, family word, `default`).
- Bot texts moved to `WORDS` (en/fr; French uses "vous"); `HELP` / `HELP_THREADS` constants removed; `setMyCommands`
  default + `en` + `fr`.
- Threads: created once `titles.pending(sid)` is false (60 s max); at most one rename in a session's first 2 min;
  an emoji-only change does not rename.
- UI: sync error toast, `#feed` labelled, confirmation with a count before lowering `thread_days`.
  Tests `test_telegram_polish.py`.


## 2.0.0-alpha.101 - 2026-10-26

#22: `cmd_core.claude_settings_defaults()` (called by `maxxing init` only) also sets `attribution` to
`{"commit": "", "pr": ""}` when neither `attribution` nor `includeCoAuthoredBy` is in Claude Code's settings.json.
`.githooks/commit-msg` = the cloud repo's hook (AI author, signature or AI co-author refused; people allowed);
CONTRIBUTING: `git config core.hooksPath .githooks`.

## 2.0.0-alpha.100 - 2026-10-26

Integration of #12, #14, #16, #19 and #21 (Radar: 20 findings, one commit each with its test; the PR body has the
table). `web/dist` rebuilt here, not merged.
- #12 `cmd_core`: `maxxing update --branch` replays the `custom:` commits on the new branch.
- #14 `pages/sessions/index.tsx`: wheel over `[data-col-head]` or Shift + wheel scrolls the strip (fine pointer only).
- #16 `pwa`: `announceUpdate` applies the waiting service worker unless a field has focus (then on focusout / tab
  hidden); the stream reconnect calls `checkForUpdate()`; Settings -> Update reloads when done.
- #19 `MediaPlayer`: touch volume (tap = open, 2nd tap = mute; iOS read-only `volume` -> Web Audio gain); Auto
  switches to the ready copy only on stalls / dropped frames, never on a refetch.
- #21: `license.remove_key()` replaces the section, hint `HM-…` + 4; `license.activate()` checks `token`;
  `feedback` email ≤ 254; `http.client.HTTPException` = network error; `register` under an RLock;
  `health.issue_id()` keeps digits in quotes, `mark_seen` under `ProcessLock("health-seen")`; `read_back()` carries
  the agent kind from `task_started`; `crons._read_raw()` = None on an unreadable file, `restore_job()` validates the
  id and the job, `managed_lines()` skips unsafe ids; `maxxingStats.rewind()`; SPA fallback 404 under `assets/`,
  `sw.js` never caches HTML for `/assets/`; `fold()` copies `tasks` once per fold; touch sizes (`pointer-coarse`).

## 2.0.0-alpha.99 - 2026-10-25

Team (`team_page`, off by default; plan: chats between people, never between Claudes).
- `maxxing/team.py`: chats in `<state>/team/team.json` (format in the module docstring), files uploaded to
  `<workspace>/team/attachments/YYYY-MM/`. DM id = `d_` + sha256(sorted addresses)[:16] (same on both servers),
  group id `g_<hex16>`, message / option ids global (`_ID`), so an event means the same thing everywhere.
  `apply_remote(frm, contact, event)` applies `chat|message|vote|react` from a peer after checking membership
  (only the group admin sends `chat`; a sender can only write as itself). `summarize(cid, ids|since)`: one
  `claude -p --output-format json --model claude-sonnet-5-5 --tools "" --no-session-persistence --strict-mcp-config
  --disable-slash-commands` in `claude-titles`, 409 `nothing_new` under 2 messages; posted as a `summary` message
  (shared with the members). `mark_sent` records "to a session" clicks.
- `maxxing/teampeer.py` (stdlib + httpx): connections, signing, outbox (protocol in the module docstring).
  `<state>/team/peers.json` (600): `peers` (address -> {key, status accepted|request|waiting, profile,
  fingerprint}), `invites` (sha256 of the code, 15 min, one use), `files` (fid -> path, shared), `outbox`
  (retries with backoff for 7 days, then dropped; `pending` on the message until delivered). Inbound: ±300 s,
  nonce replay cache, 240 req/min/IP, 5 bad hellos/h/IP -> 429. Outbound: https + public IP only; Tailscale
  (100.64/10, `*.ts.net`) and private ranges refused (`readiness()` reasons `no_address|not_https|tailscale|local`).
  `team_insecure` / `MAXXING_TEAM_INSECURE=1` lifts this for local tests. Files: signed GET, capped by `upload_max_mb`.
- `api/team.py` (auth) and `api/teampeer.py` (public `/api/team-peer/{hello,inbox,files/<fid>}`, 404 while
  `team_page` is off, listed in `bodylimit._public`). `startup()` starts the outbox worker.
- Web: `features/team/` (TeamPage `/team` in `FEATURE_NAV`, TeamPanel = right column in `AppShell` toggled from
  `TeamNavExtra` in the sidebar, localStorage `mx-team-open` + `mx-team-chat`), dictionary group `team`, bus topic `team`.
- Tests: `tests/test_team.py`, `tests/test_teampeer.py`. Checked end to end with three local servers.

## 2.0.0-alpha.98 - 2026-10-24

Pull request #15 (tabs view), web only.
- `web/src/pages/sessions/Tabs.tsx`: `TabsToggle`, `TabsBar` (chips of `cols`, state from the sessions list,
  cross = `close(key)`, "Waiting" = first other col whose session is not running and is unread or in error),
  `TabsArrows` (computer, edges of the strip), `useSwipe` (phone: > 70 px sideways in < 600 ms, ignored over an
  element that scrolls sideways or a text field), `MobileTabsSlot` (context: the session layer hands the chips to
  the mobile header of `Column.tsx`, between the app bar and the title).
- `store.ts`: `tabs` (persisted in `mx-sessions`, default false, no version bump: unknown = default).
- `index.tsx`: in tabs view every column is placed in the single grid cell with `Place.hidden` for all but the
  focused one (`hidden` class in `ColumnShell`): columns stay mounted (no thread reload, scroll kept) and `cols`,
  `widths`, `below`, `wide` are never touched, so turning it off shows the same strip. FLIP skipped while on;
  grid / layouts button hidden. Alt+T toggles; Alt+Left / Right unchanged (they move the focus, hence the tab).
- Phone: a chip navigates (`/sessions?path=…&session=…`, replace) like the session list.
- Adapted at integration: the `maxxing` namespace (Maxxing mode, beta, off by default) is a dictionary group of
  its own (`groups.ts`), loaded once its controls show: the French first load of `/sessions` was over the 20 kB
  budget of `test_web_first_load` (already on `beta`, 20 086 B; 20 185 B with the tabs texts).

## 2.0.0-alpha.97 - 2026-10-24

Pull requests #6 and #7 (FEU), merged as they were.
- #7 Removed cron jobs kept: `crons._save_raw(jobs, reason)` calls `_remember()` before and after the write; it
  compares with `<state>/crons/jobs.seen.json` (the list as last written or synced) and appends every job gone to
  `<state>/crons/deleted.jsonl` (`{at, reason, job}`, last `MAX_DELETED` = 200), reason `deleted` (from
  `delete_job`) or `vanished (jobs.json edited outside Harness Maxxing)` (noticed at the next save or at
  `sync_crontab()` without a job list). Never raises; warning in the server log. `crons.deleted_jobs()`,
  `crons.restore_job(id)` (CronError `exists` / `not_found`); CLI `maxxing cron deleted` and
  `maxxing cron restore <id>`. Existing installs start the trace at their first save (no `jobs.seen.json` yet).
  Skill `maxxing-cron`: hand edits read and write in one step under `flock <state>/.crons.lock`.
  Tests: `test_crons.py::test_removed_jobs_are_kept_and_restored`, `test_a_hand_edit_noticed_at_the_next_save`.
- #6 `health.cpu_pct()`: after a pause of more than 10 min the 0.1 s sample fell into the "calls closer than 1 s
  repeat the last value" guard and never saved the new baseline, so the value stayed frozen; the guard is now an
  `elif`. Test: `test_system.py::test_cpu_after_a_long_pause_is_measured_again`.
- Docs: `28-mcp.md`, `<service>` and `<your PC>` in code spans (they vanished in the HTML of the public docs).

## 2.0.0-alpha.96 - 2026-10-23

Pull requests #3, #5 and #4 (FEU), adapted at integration.
- #5 Foreground subagents: config `background_agents` (default **false**). `spawn.agents_args(cfg)` adds
  `--append-system-prompt FOREGROUND_AGENTS` (always `run_in_background: false` unless the user asks) to every turn
  (`runner.py`); `[]` when `background_agents` is true. Behavior change for every installation (upgrade note).
  `tests/fake_claude.py` parses `--append-system-prompt`. Tests: `test_spawn_tuning.py`,
  `test_sessions.py::test_turns_ask_for_foreground_agents`.
- #4 Maxxing mode (web only): `pages/sessions/maxxing.ts` (zustand store `mx-maxxing` persisted `{on, saved}`: queue
  of finished sessions, `current`, `history` for Back, `useMaxxingDriver` ticking every 500 ms), `maxxingStats.ts`
  (10 min window: 70 % utilisation, 30 % answer delay, score up to 1.1), `MaxxingMeter.tsx` (`MaxxingControls`,
  `MaxxingMeter`), store `solo(id)` / `restoreLayout(saved)`, `prefetchTail` refreshes a tail older than 10 s, CSS
  `mx-liquid` / `mx-meter-*`, mock scenario `maxxing` (`MOCK_PASSWORD`, `MOCK_DIST`).
  Adapted at integration: config + settings key `maxxing_mode` (default false, `api/settings` KEYS / `SettingsIn`
  / `current()`, `backup.RESTORABLE_CONFIG`), Settings -> Features row "Maxxing mode (beta)" (i18n
  `features.maxxing|maxxingDesc`); `useMaxxingEnabled()` gates `MaxxingControls`, `MaxxingMeter`, the driver (now
  mounted as `<MaxxingDriver>`) and Alt+M (also hidden from the shortcuts help); setting off while a browser has
  `on` -> `setOn(false)` (layout restored). Bug fixed: in the touch layout `[data-touch-layer]` always exists, so
  `current` was never released; the session on screen is now read from the URL (`?session=`).
  Test: `test_settings.py::test_maxxing_mode_is_an_opt_in_feature`.
- #3 Touch layout: plan mode button (`ListChecks`) next to the session title in `ColumnHeader` (mobile), removed
  from the **…** menu; `aria-label` = `plan.toggle` (state in `aria-pressed`, like desktop).
- Docs: user 04 (plan button, Maxxing mode), 11 (foreground agents, Features), API.md (`maxxing_mode`), DESIGN.md
  (mock scenario).

## 2.0.0-alpha.95 - 2026-10-23

Health issues marked as seen + smooth column snap (maintainers' request).
- `health.py`: every issue gets `id` (sha1 of code + text without digits, 12 chars) and `seen`; marks in
  `<state>/health-seen.json` `{id: at}`, kept while the issue is there and for `SEEN_TTL_S` (24 h), pruned at each
  collect. `mark_seen(id, seen)`. `POST /api/system/health/seen {id, seen=true}` -> fresh health (`404 not_found`
  when no current issue has that id), bus `health`. `ok` unchanged (all issues).
- Web: `openIssues()` = issues not seen; `healthTone` and the count use them (sidebar, touch menu); the popover lists
  all, seen ones greyed with an undo button. `useMarkHealthSeen` (optimistic). i18n `health.markSeen|seenHint|unsee`.
- Sessions strip: after a sideways wheel / swipe, `glideToColumn` smooth-scrolls to the nearest column start when it
  is within 30 % of the strip width, then turns `scroll-snap-type` back on (it used to jump there); a new wheel
  event cancels the glide; reduced motion keeps the old behaviour.
- Tests: `test_system.py::test_health_issue_marked_seen`. Docs: user 04, 16.

Background agents visible in the thread. Claude Code's `system/task_*` lines (task_started / task_progress /
task_updated / task_notification), dropped until now, become a normalised `task` event.
- `sessions/normalize.py` `_task()`: partial `{type:"task", id, tool_use_id?, state?, kind?, background?,
  description?, agent_type?, activity?, last_tool?, tokens?, tools?, duration_ms?, summary?, at}` (API.md, Event).
  `killed` -> `stopped`; `summary` (the agent's report) clipped at 20 kB; lines with `owned_by_subagent` dropped;
  a `task_updated` without status / background change dropped. Stateless per line, so old logs show it too.
- `service.read_back`: `task` events do not count toward `tail` / `limit` (a busy agent writes a progress line every
  few seconds: they would push the thread rows out of the first page).
- Web: `log.ts` folds them into `LogState.tasks` (by task id) and `item.task` on the tool item of its `tool_use_id`
  (`foldBefore` merges both pages, newer fields win). A `user` row (= a new Claude process) marks the tasks still
  running `interrupted`; `taskStatus()` also says interrupted when the session no longer runs. Shown: agents, and
  commands with `background` (a foreground command already is its own tool line).
- `Tasks.tsx`: `TaskDetails` (in the opened card; the "Async agent launched" tool result is hidden), `TaskBar`
  (pill above the composer + popover, `data-testid="task-bar"`; a click dispatches `mx-open-task`, the card opens
  and scrolls into view), `TaskElapsed`. `RunningRow` says "n running in the background" instead of "Working…" when
  nothing else is pending. i18n `tasks.*`.
- `tests/fake_claude.py`: `AGENTS` (two background agents + a background command, `FAKE_CLAUDE_AGENTS_S`). Tests:
  `test_session_logs.py` (normalisation, tail counting, end to end).
- Docs: user 04 (What you see).

## 2.0.0-alpha.94 - 2026-10-22

Anonymous counter on by default, out of the onboarding, enriched payload, environment opt-out.
- `register.DEFAULTS["count"]` = `True`. `register.migrate(raw)` (called by `cmd_core.do_init`, so by every
  `maxxing update` through the new code's init, and by the installer): once, guarded by config
  `register_migrated_a94`, sets `register.count = true` when `register.asked` is false or `register` is missing;
  installs with `asked: true` keep their `count`. Fresh installs get the flag on their first init.
- `register.blocked()`: `MAXXING_NO_TELEMETRY` or `DO_NOT_TRACK` set to anything but ``/`0`/`false`/`no` = counter off
  whatever `count`. `counting()` = `count and not blocked()`; every "is the row wanted" test uses
  `counting() or email`. `heartbeat_due()` is also true when a token is left while nothing is wanted (opt-out set
  after a count-only registration): `heartbeat()` then goes through `sync()`, which deletes the row.
- Payload (POST `/v1/register` and `/v1/heartbeat`) when counting: `os` (`NAME VERSION_ID` of `/etc/os-release`, else
  `PRETTY_NAME`, else `platform.system()`, sanitized, <= 40 chars), `arch` (`platform.machine()`, <= 16), `health`
  (<= 10 codes matching `^[a-z_]{1,24}$`, from the cached `health.collect()`: `service_ok`/`service_down`,
  `claude_signed_in`/`claude_signed_out`, the other issue codes, `update_failed` when `customs.pending()` has a
  reason, `telegram_on`, `backup_on`; `health_unknown` if the health check raised). Register with an email but the
  counter off sends `os`/`arch`/`health` = `null` (clear). The old cloud ignores unknown fields (`fields()` picks
  known keys; heartbeat reads `token` + `version`).
- `GET/PUT /api/settings/register` gains `count_blocked`. Web: `RegisterFields` props `counter` (false in the
  onboarding: email + news only; the step no longer sends `count`) and `counterBlocked` (checkbox disabled + note).
  New i18n keys `register.countBlocked`, `onb.profile.counterOn`.
- Tests: `tests/test_register.py` (defaults, payload keys and no pseudo/path/hostname/IP for count-only, heartbeat
  payload, migration asked / not asked / once, `do_init`, both opt-out variables, `os_name` parsing and length,
  health code format).

## 2.0.0-alpha.93 - 2026-10-22

Dead code of the paid / signed-archive model removed (fair source since a85-a88); third-party notices.
- Removed from `maxxing/license.py`: `PUBKEYS` / `pubkey` / `DEFAULT_KID`, `_url_ok`, `check` (`/v1/update`), `ping`
  (`/v1/ping`) + `health_summary` + `ping_due` + `PING_EVERY`, `_rotate`, `signed_message`, `verify_signature`,
  `_verify_with`, `download`, `_extract`, `import_release`, `remote_version`, `is_downgrade`, `fetch_latest`.
  `MAXXING_RELEASE_PUBKEY` is gone.
- Why it is dead: a server only runs this code after a git update, or after its OLD code (a31..a86, still on
  archives) installed the newest signed archive. In both cases the archive download / verification is done by the
  code that fetched it; this code only has to move the server to git.
- Kept for those servers: `enabled()` (`license_token` = still on archives), `move_to_git` / `try_move_to_git` /
  `move_due` / `_git` / `_version_at`, `GIT_URL`, `PRE_GIT_REF`, and the triggers: `api/system._after_update` (every
  start, after `MAXXING_MOVE_QUIET_S`, never while `maxxing-update` runs), the hourly `_ping_loop` (now only the move
  and the registration heartbeat) and `cmd_update`. Kept for the Enterprise key: `activate`, `release`,
  `remove_key`, `status`, `machine_id`, `os_name`, `_post`, `API`, `USER_AGENT`, `disk_version` (register,
  feedback).
- `release()` no longer forgets `license_token` (it is the marker of the move still to do).
- `cmd_update` on an install still on archives: saves uncommitted non-`web/` changes as a customization, then
  `try_move_to_git`; on failure exit 1 with the reason (before: fell back to the archive download). Moves even with
  `--branch`. `--allow-downgrade` and `_ALLOW_DOWNGRADE`, `_report_version` (ping after an update) removed.
  `_fetch` / `_fetch_quiet` / `api/system._refresh_remote` fetch nothing while `enabled()`; `check_update` returns
  `ok: false` with the reason. Doctor: `license` check = INFO "moving to the public git repository" (+ `move_error`),
  `update_signature` check skipped until the move.
- CLI: `maxxing license check` and `ping` removed; `activate --no-fetch` kept as a hidden no-op (install.sh passes
  it, the old code of a pre-a87 install understands it); `status` of an install still on archives says it moves.
- `install.sh`: removed `license_activate`, `machine_hash`, `json_get`, `release_pubkey`, `release_verified`,
  `fetch_release`, `ver_lt`, `RELEASE_KIDS` / `RELEASE_PUBKEY_k1`, `MIN_VERSION`, `RELEASE_JSON` (all unreachable since
  a88). `LICENSE=HM-...` still records the key at the end (`maxxing license activate --key-from-stdin --no-fetch`);
  a re-run on an install still holding `license_token` keeps its code (`LICENSED=1`, it moves by itself).
- Tests: `test_license.py` rewritten without archives (fake `/v1/activate` + `/v1/release` only); the old code's
  archive install is simulated in the test (`_old_code_installs_archive`).
  `test_an_old_server_that_installs_this_version_from_an_archive_ends_on_stable` runs the start trigger
  (`system._after_update`) on such a server and checks `stable`, upstream, customizations, key and seat, then a plain
  git update. Release-key tests of `test_install_security.py` removed.
- Server side (cloud, unchanged): `publish.py` keeps producing the signed archive, the bridge of the servers still on
  archives; `/v1/update` and `/v1/ping` stay for their old code.
- `scripts/third_party_notices.py` (stdlib) -> `THIRD_PARTY_NOTICES.md`: Python packages of `uv.lock` (runtime +
  `voice` extra, markers evaluated for Linux / CPython 3.12; texts from the dist-info of `server/.venv`, else the
  package's top-level LICENSE from RECORD), JS production dependencies of `web/package.json` and their transitive
  production deps (`package-lock.json`, texts from `node_modules`) plus `vite` / `tailwindcss` (code embedded in
  `web/dist`, own license only), Go modules of `pc-agent/go.mod` (module cache if present, else a known license id
  + pkg.go.dev link). Fonts = the `@fontsource-variable/*` packages (OFL-1.1). Sorted, identical texts merged,
  `--check` mode. CONTRIBUTING + README mention it. No GPL / AGPL / LGPL found; weak copyleft: MPL-2.0 (certifi,
  tqdm with MIT, dompurify as MPL-2.0 OR Apache-2.0).

## 2.0.0-alpha.92 - 2026-10-22

Donate restyled (maintainers' request). Web only, no API change.
- Icon `HandHeart` (lucide) instead of `Heart` everywhere (sidebar, ⊞ menu, `DonateButton`, Settings -> Support,
  `SETTINGS_SECTIONS`). `DONATE_TONE` = accent classes (`border-primary/30 bg-primary/10 text-primary`), no pink.
- Sidebar: `DonateLink` = ghost icon button (`size-8`, `text-primary`) after `UserMenu` in the bottom icon row (tooltip
  "Donate · …"), no longer a row above Feedback. ⊞ menu: the Donate row is `text-primary`.
- `SETTINGS_SECTIONS`: `support` last (after `docs`); its nav item (sidebar list and phone tabs) is `text-primary`.
- Docs: user 23.

## 2.0.0-alpha.91 - 2026-10-22

Donate buttons more visible (maintainers' request). Web only, no API change.
- `features/donation/Donation.tsx`: `DONATE_TONE` (pink tinted classes), `DonateButton` (link styled as a button, Heart +
  ExternalLink, hidden with `donation_hidden`); `DonationLine` = sentence + `DonateButton` (prop `link` removed; i18n
  `donation.link` / `donation.feedbackLink` removed, `donation.feedback` is now a full sentence).
- Sidebar: `DonateLink` above Feedback (collapsed = heart only, tooltip `settings.support.desc`); touch ⊞ menu
  (`TouchNav.AppPanel`): Donate row before Feedback. Both hidden with `donation_hidden`.
- i18n `donation.hide` / `donation.hideDesc` say "Donate buttons". Docs: user 11 + 23.
- Website (cloud, deployed separately): `/donation` shows one tab per way to pay.

## 2.0.0-alpha.90 - 2026-10-22

Donation links (links only, no payment code). The donation page itself is on the website (`/donation`: Lightning
offer + Bitcoin address set in the admin, optional "I made a donation" note to the admin Inbox).
- Config `donation_hidden` (default false, `config.DEFAULTS`), in `GET/PUT /api/settings` (`SettingsIn`, bool, 422
  otherwise). Tests: `tests/test_settings.py::test_donation_hidden` + defaults.
- UI: `features/donation/Donation.tsx` (`DONATION_URL`, `donationUrl(lang)` adds `?lang=<lang>` except for en,
  `useDonationShown()` = settings loaded and not hidden, `DonationLine`, `target=_blank rel=noopener`). New Settings
  section `support` (`pages/settings/sections/Support.tsx`, Heart icon, after License): card + Donate button + switch
  `donation_hidden`. `DonationLine` in `WhatsNewDialog` (footer, next to "All updates"), the sent state of
  `FeedbackDialog` and the first card of `License.tsx`. i18n core keys `settings.support*`, `donation.*`. Mock server
  knows `donation_hidden`.
- `.github/FUNDING.yml` (GitHub "Sponsor" button -> the donation page); README "Support the project"; docs/user 11 +
  23; help topic template index (23-license.md row).

## 2.0.0-alpha.89 - 2026-10-22

Feedback to the authors (Romain's request).
- `maxxing/feedback.py`: `send(email, type, message)` -> cloud `POST /v1/feedback` (`register._call`, `license.API`,
  user agent `harness-maxxing/<v>`) with `{email, type: bug|idea|other, message <= 4000, version, lang, name (profile
  pseudo)}`; `FeedbackError(code, message, status)`; offline guard = `register._offline()` (`MAXXING_LICENSE_PING=0`);
  the last email is kept in config `feedback_email`, defaults to `register.email`.
- `GET /api/settings/feedback` (`{email, version}`), `POST /api/settings/feedback` (400 invalid_email /
  message_required / too_long, 429 rate from the cloud, 502 unreachable, 503 offline).
- UI: `components/shell/FeedbackDialog.tsx` (lazy, i18n group `feedback`, open state `feedback-store.ts`), mounted
  by `FeedbackHost` in `AppShell` on first open; `FeedbackButton` in `Sidebar.tsx` (above the icon row; icon only
  when folded); row in the touch app drawer (`TouchNav.tsx`). Core keys: `shell.feedback`, `shell.feedbackHint`.
- `system.licenseKind.enterprise` (License page, System version card).
- Cloud (`harness-maxxing-cloud` `a3865b8`): `/v1/feedback` (10/h per IP, 10/day per email, ack email), stored as
  lead kind `feedback` (`subject` = type, `leads.version`, migration 0011), admin Inbox tab Feedback, alert emailed to
  the admins with reply-to = sender.

## 2.0.0-alpha.88 - 2026-10-22

Fair source step 6.4: the license key is an optional right of use (Enterprise), never a delivery channel.
- `license.activate` (cloud `/v1/activate` unchanged: checks the key, counts the machine) stores the token as
  `license_seat` (only to free the seat: `release`, `remove_key`) instead of `license_token`, unless the install
  is still on archives. `enabled()` (= archives) is therefore never turned on again. `move_to_git` keeps the seat
  (token -> `license_seat`). `remove_key()` = release (best effort) + forget key, seat and license info (keeps
  `moved_to_git`). `status().has_key`. `try_move_to_git` no longer records "already moving" (both triggers met on
  the demo server).
- `GET/PUT/DELETE /api/settings/license` (bus `license`); `/api/system/version` license adds `moved_to_git`,
  `move_error`.
- CLI: `maxxing license status` for a git install shows the key (or "no Enterprise key") and the update source;
  `activate` records the key and fetches nothing unless the install is still on archives; new `remove`.
- UI: Settings -> License (`LicenseSection`, `features/license/LicenseKey.tsx`: who needs a key, key field, remove);
  onboarding About you: box "I have an Enterprise license key" -> the same field, saved on Next (cloud message shown
  under the field on refusal).
- `install.sh`: `BRANCH` = `stable` always; `LICENSE` no longer selects signed archives (choose_source), it is
  recorded at the end with `maxxing license activate --key-from-stdin`. A re-run on an install still holding
  `license_token` keeps it (it moves to git by itself). `publish.py` unchanged: the archive stays the bridge for
  installs still on archives; `install.sh` is served from the same upload.

## 2.0.0-alpha.87 - 2026-10-22

Fair source step 6.3: licensed installs leave the signed archives for the public repository.
- `license.move_to_git()` (lock, never raises): refused while a rebase / pending update / uncommitted change /
  detached HEAD; base = merge-base(HEAD, synthetic `origin/<branch>`) (a fetched-not-installed archive is
  ignored); `origin` = `MAXXING_GIT_URL` (default `makushingu/harness-maxxing`), fetch `stable` only; target =
  the `stable` commit with the same tree, else the newest with the same `__version__` (last 500); old HEAD in
  `refs/maxxing/pre-git`; `checkout -b stable` + `rebase --onto target base` (customizations; abort and back to
  the old branch on conflict); upstream `origin/stable`; old branch and synthetic ref deleted; `license_token`
  forgotten (key kept). `try_move_to_git()` records `license.move_error` / `move_tried_at` (retry after 6 h,
  `move_due`).
- Triggers: `_after_update` and the hourly `_ping_loop` (`_move_to_git`: 5 min after the server start,
  `MAXXING_MOVE_QUIET_S`, and never while the `maxxing-update` unit runs), and `maxxing update` (before choosing
  the branch, unless `--branch`). Doctor `license` check shows `move_error`.
- Tried for real on a copy of the demo server (a85 licensed): moved to `0b19e196` (same version, other files),
  then a plain git fetch saw a86.

## 2.0.0-alpha.86 - 2026-10-22

Fair source step 6.2: optional registration of servers with the cloud (`/v1/register`, `/v1/heartbeat`, cloud
table `installs`, admin Users page).
- `maxxing/register.py`: config `register` `{count, email, news, asked}`, `register_meta` `{error, synced_at}`,
  token `register_token` in `secrets.json` (never the Keys vault). `sync()` creates / updates / unregisters the
  cloud row to match the settings (pseudo of `profile` and `ui_lang` sent only with an email); `heartbeat()` once
  a day from `_ping_loop` (`heartbeat_due`). Cloud answers `unknown_install` (archived from the admin) -> token
  forgotten, registered again. `MAXXING_LICENSE_PING=0` = never calls the cloud (tests, air-gapped).
- `GET/PUT /api/settings/register` (bus `register`); `/api/onboarding` `steps.profile` = `register.asked`.
- UI: onboarding step "About you" after the language (count checked by default, email empty, news unchecked),
  Settings -> Profile card with status line and "Stop, don't contact me" (= everything off + DELETE on the cloud,
  which archives the row: `deleted_at`, never contacted again, kept for us; erasure on request).
- Never enabled by an update: `register` absent = nothing sent, the onboarding step only shows to new installs.

## 2.0.0-alpha.85 - 2026-10-22

The repository moved to the GitHub organisation `makushingu` (`makushingu/harness-maxxing`, still private until
the history is cleaned); `stable` branch for installs without a key.
- New address everywhere: `install.sh` (`REPO`), `cmd_core` doctor hint, `pc_agent.json` (binaries URL), README,
  CONTRIBUTING, SECURITY, issue template, docs 02 and 23. GitHub redirects the old address (git and web), so
  existing installs keep updating; the upgrade note repoints their `origin` anyway.
- `install.sh`: `BRANCH` defaults to `stable` without `LICENSE` (published versions only; `main` = work in
  progress, FEU's PRs land there first), `main` with a license key as before (signed releases, branch name local
  only). `maxxing update` follows the checked-out branch, so nothing changes in the server.
- Publishing (cloud `scripts/publish.py`, not `--beta`) now also pushes the published commit to `stable`,
  fast-forward only.

## 2.0.0-alpha.84 - 2026-10-22

FEU's PRs #86-#91 integrated (one commit per PR, without their version files; #86 was numbered a84 too).

### #86 Radar fixes
- `mcp._write_cfg` takes Claude Code's lock (`.claude.json.lock` folder, proper-lockfile style; stale after 10 s, waits 10 s at most) and a process lock, then re-reads before replacing the file.
- `mcp._write_cfg` writes to `_cfg_path().resolve()` (temp file and lock next to the real file), so a symlinked `.claude.json` is no longer replaced by a plain file.
- `mcp.restore` skips an item whose `config` is not an object and also catches `ValueError` (`dict("abc")` in `_redacted` stopped the whole restore).
- `mcp.REF_RE`: the `${KEY:-default}` default stops at the next `$` (`[^}$]*`), linear instead of quadratic on `${A:-` repeated without `}` (100 kB: 33 s -> a few ms). A default containing `$` is no longer a reference (treated as literal text, so masked).
- `backup.configure` refuses a token outside printable ASCII (`TOKEN_RE`, 1-255 chars) before any call: `httpx` raised `UnicodeEncodeError` on the `Authorization` header (500).
- `backup.run` stages with `git add -A --force`: a `.gitignore` copied from the workspace (or a global excludes file) dropped collected files while the run said ok.
- `backup._apply.put` catches `OSError` (folder in place of a file, file in place of a folder...): the `.restore-tmp` is removed, the path goes to the new `skipped` list of the restore result (API.md), the rest goes on.
- `pcbridge._state_lock` (RLock) around every read-modify-write of devices.json (`set_settings`, `start_pairing`, `pair`, `_confirm_state`, `_touch_device`, `_unpair_state`): the hello of a reconnecting agent wrote the device back after an unpair.
- `pcbridge.Hub.serve` catches `TypeError`/`ValueError`/`AttributeError`/`KeyError` raised by `_on` for one frame (`browsers: 5`, `d: 5`...) and logs it; the websocket stays open.
- `api/pc._rpc`: `params` or `tools/call` `arguments` that are not objects -> JSON-RPC `-32602` (was `AttributeError`, HTTP 500).
- `cmd_update`: the `customs.CustomError` exit of the auto-save pops the web/ stash first (`_unstash_web()`, shared with `_back_to`).


### #87 Connect button in the chat
- `web/src/features/mcp/AuthButton.tsx`: a tool card `mcp__<server>__authenticate|complete_authentication` (Items.tsx)
  shows the sign-in of the matching http/sse server of `/api/mcp`. `ConnectDialog` moved out of
  `pages/settings/sections/Mcp.tsx` into `features/mcp/ConnectDialog.tsx` (unchanged).

### #88 harness-pc for every turn
- `pcbridge.mcp_config_args()`: when a PC is paired, each turn gets `--mcp-config <state>/pc/mcp-config.json` (0600,
  the secret stays out of the process list), since ~/.claude.json is rewritten by every running Claude process.
  `pcbridge.ensure_mcp()` puts the user entry back when it is gone (at most every 30 s). `MAXXING_LISTEN_PORT`
  forwarded to the runner.

### #89 Delete dialog
- The name to type is a button that fills the field; Enter in the field confirms when it matches (not while composing).

### #90 Wheel over the session strip
- A vertical wheel outside every `[data-col]` scrolls the strip sideways (fine pointer only); inside a column unchanged.

### #91 Automatic update when idle
- `maxxing/auto_update.py` (INTERNALS.md), config `auto_update` (default false, nothing writes it on existing installs),
  `PUT /api/system/auto-update`, `bus.browser_count()`.

### Adapted at integration (wins over the notes above)
- #91: `tick()` returns `not_on_branch` on a detached HEAD (`on_branch()`: our test workflow puts a branch there; the
  preflight read it as branch `HEAD` -> `origin/HEAD`, listed the test commits as customizations and would have rebased
  them onto main unattended) and `pending` while `customs.pending()` (a rolled-back version was retried every 24 h,
  with a restart each time). Tests `test_never_moves_a_branch_under_test_nor_retries_a_pending_update`,
  `test_branch_and_pending_read_the_real_state`. User doc: docs/user/20-customizing.md "Automatic updates".
- #86: `mcp._cfg_lock` spun forever at 100 % CPU (holding `_write_lock`, so every MCP add/rename/remove hung) on a
  stale `.claude.json.lock` it cannot `rmdir` (a file, a full folder): `except OSError: continue` skipped the deadline.
  Only `FileNotFoundError` retries now; other errors wait for the deadline and write without the lock.
- #86: `backup._apply.put` moved the file in place to the trash, then a failed write left it there (restore "ok",
  file gone; `jobs.json` lost -> crons gone at the next sync). The file goes back in place when the write fails.
- #88: `ensure_mcp()` ran synchronously in `spawn.start()` (`claude mcp add-json`, up to 60 s + the 10 s lock wait)
  although the turn already has `--mcp-config`: now `ensure_mcp_soon()` (daemon thread, `_ensure_lock` so two turns
  do not repair at once). An unpair during the repair left a dead `harness-pc` entry forever: removed again
  (`_remove_mcp`, shared with `unregister_mcp`) when the device is gone after the add.
- #87: the button stays (outline) when the last `/api/mcp` check said "connected": the agent asks because the sign-in
  expired since, and the old "is connected" text left no way to reconnect from the chat.

## 2.0.0-alpha.83 - 2026-10-22

Result line under each answer (users took the cost for a bill).
- Setting `result_line_hidden` (config.json, default `[]`, `GET/PUT /api/settings`): subset of
  `model|duration|cost|tokens|cache`, validated by pydantic (unknown = 422), de-duplicated and stored in canonical
  order. Install-wide (not the per-browser `mx-ui` store) so phone and desktop show the same line.
- `web/src/pages/sessions/resultLine.tsx`: `useResultLine()` (hidden fields + toggle through the optimistic
  `useSaveSettings`), `useCostIsBilled()` (`claude.auth.method === 'api_key'`; subscription or unknown = "estimate,
  not billed"), `costTip()`, `ResultLineMenu` (⚙ dropdown with checkbox items, `md:` hover-only, `max-md:` always).
- `ResultRow` (Items.tsx): every part has a wrapped tooltip; tokens and cache share are two parts now. Hiding `cost`
  also hides the session total in both column headers, whose tooltip uses `costTip()` (key `sessions.costTip`
  removed). Settings -> General -> Appearance: `ResultLinePicker` (checkboxes).

## 2.0.0-alpha.82 - 2026-10-22

FEU's PRs #84 and #85 integrated (one commit per PR, without their version files; #85 was numbered a82 too), and
the fair source / keyless install of PR #83 (already on `main`, merged without a version) shipped with its public
`CHANGELOG.md` entry.

### Fair source (PR #83, merged before this release)

Fair source (merged without a version bump: `tests/test_docs.py::test_all_updates_in_settings` wants the top `CHANGELOG.md`
entry to be the current version, so the public entry is added by the release that ships this, with
`docs/upgrade/<version>.md` "Nothing to do").

- `LICENSE`: Harness Maxxing Fair Source License 1.0. New `CONTRIBUTING.md`, `CLA.md`, `CODE_OF_CONDUCT.md`,
  `SECURITY.md`, `.github/` (PR and issue templates), `docs/dev/workflows/` (`ci.yml`: server pytest, web typecheck+build, pc-agent
  `go test`; `cla.yml`: CLA Assistant Lite, signatures on the branch `cla-signatures`) - to move to
  `.github/workflows/` with a token that has the `workflow` scope (see `docs/dev/workflows/README.md`).
- install.sh: the code source decision moved into `choose_source()` (testable in library mode). A new install
  without `LICENSE` nor `GH_TOKEN` no longer asks for a key: it clones `github.com/$REPO` with plain git (public
  repository, `fetch_code` already supported it). `LICENSE=HM-…` -> `license_activate` + signed release as before;
  an existing install with `license_token` in secrets.json stays licensed; `GH_TOKEN` = private fork / mirror.
- `cmd_core.check_license()`: never `WARN` without a license (`INFO` "updates from the git repository" when
  `update_source() == "git"`, else "local copy"). `check_update()` without a source: message "no git remote",
  hint `git remote add origin https://github.com/rorogeno/harness-maxxing.git`. `maxxing license status`
  without a license: `INFO`, not `WARN`.
- Unchanged: the daily `/v1/ping` only runs when `license.enabled()`; Settings -> System shows the license line only
  when `license.enabled` (no web change, `web/dist` not rebuilt).

### #84
- Rename of a project/topic: the web (`CreateProjectTopic.tsx`, `Tree.tsx`) maps 409 `exists` to `workspace.exists`
  and 409 `has_running_sessions` to the new `workspace.hasRunningSessions` (before, every 409 read "already
  exists"). Test `test_rename_running_topic_is_not_reported_as_existing`.

### #85 (Radar fixes)

#### responsive

- `Tree.tsx` `TouchHeader` chips: `max-md:h-10` (were 32 px).
- `Thread.tsx` jump-to-bottom pill: `max-md:h-10 pointer-coarse:h-10` (was 32 px).
- `files/Listing.tsx` row ⋯ trigger: `max-md:size-10 pointer-coarse:size-10` (was 36 px, tablet included since a76).
- `Items.tsx` `VoiceNote`: the transcript wrap classes sit on an inner `<span>`; `Sensitive` renders a fragment (no `className`) outside presentation mode.
- `Items.tsx` `VoiceNote` mic button and `MediaPlayer` `IconButton` / `PickButton`: `max-md`/`pointer-coarse` size 40 px; the seek bar hit area is 32 px tall on touch (track unchanged).
- `PcBrowserCard.tsx` pairing view: `grid-cols-[minmax(0,1fr)]` on its grids (auto tracks grew to the command width, so `truncate` did nothing), `min-w-0` on the command block.
- `PcBrowserCard.tsx` paired view and recent actions list: `grid-cols-[minmax(0,1fr)]` (the 5-option `Segmented` widened the auto track past the card); a long tool name in a recent action's badge is truncated (`max-w-[45%]`).
- `UpdatePlan.tsx` `verifyLong` link: `shrink whitespace-normal text-left`; `Callout`: text column `flex-[1_1_12rem]` + `flex-wrap`, so a wide `action` goes under the text when the row is too narrow (unchanged when it fits); Version card grid and the update plan box/list get `grid-cols-[minmax(0,1fr)]` (a truncated file path widened the auto track past the card).

#### security

- `sessions.service._check_voice`: the resolved `voice` path must be inside `config.workspace()` under an `attachments/` folder (symlinks resolved), else 400 `bad_attachment`. Before, any absolute file was accepted and `voicejobs` remuxed a `.webm` in place wherever it was. Test `test_voice_path_outside_the_workspace_attachments_is_refused`.
- `mcp.parse_id`: a `project|<folder>|<name>` id needs an absolute folder that resolves inside the workspace, else 400 `bad_id` (`remove()` rewrites `<folder>/.mcp.json`; an empty folder meant the server's working directory). Test `test_project_server_id_outside_the_workspace_is_refused`.
- `backup.clean_include` / `clean_schedule` are shared by `update_settings` and the restore of `_maxxing/config.json` (before, `backup.include`/`schedule` were copied unchecked: absolute or `..` patterns, any schedule). Patterns: a list of at most 100, each ≤ 200 characters with at most 3 `**` (each is a `.*` the regex backtracks over: `"**a"*14+"**c"` looped `collect()` with the lock held); an invalid restored value keeps the current one. `glob_re` collapses `**/**/` and `***`; `collect()` and the restore hold skip a saved invalid pattern. Tests `test_restored_backup_settings_get_the_settings_checks`, `test_backtracking_include_pattern_is_refused_and_skipped`.
- `pcbridge._bad_url`: tabs/newlines dropped and `\` read as `/` (as the browser does); an http(s) URL must be `scheme://host…` with a host (`http:host`, `http:/host`, `http:///host` gave urlsplit no host, the browser one). `_local_host`: NFKC + ideographic dot, international names through IDNA, a `%` in the host refused, loopback DNS helpers (`LOOPBACK_DNS`: nip.io, sslip.io, localtest.me, lvh.me…) refused. Tests: `test_local_network_of_the_pc_is_refused` (14 more cases), `test_internet_pages_are_allowed` (IDN, userinfo).
- `cmd_core.valid_branch` (the rules of install.sh `check_inputs`): `_fetch` refuses another name and `_fetch`/`_fetch_quiet` pass `--` before the branch (before, `maxxing update --branch '--upload-pack=…'` ran a command through `git fetch`). Test `test_update_branch_is_never_a_git_option`.

### Adapted at integration (wins over the notes above)
- #85: `backup.clean_include` also refuses a pattern with more than 16 `*` (`MAX_STARS`): each single `*` is a
  `[^/]*` and `"*a"*30+"*c"` backtracks like `**` did (cap of 3 `**` alone left it open). Our default patterns use
  at most 2. Tests: one more case in `test_restored_backup_settings_get_the_settings_checks`, and in
  `test_backtracking_include_pattern_is_refused_and_skipped`.
- Left open (not a regression, noted for the PC agent): `_bad_url` only filters the `url` argument; a public page or
  a `data:` page redirecting to a local address, `evaluate_script`, or any DNS name resolving to a private IP still
  reach the PC's network. To close in the agent (`cdpfilter.go`: host + resolved IP on `Page.navigate` and
  redirects) before publishing its binaries. Symlinked topics pointing outside the workspace: their direct voice
  messages and project MCP servers are now refused (400), accepted as a rare case.

## 2.0.0-alpha.81 - 2026-10-21

FEU's PRs #79 (its 2 commits pushed after the SHA frozen for a80), #81 and #82 integrated (one commit per PR,
without their version files; numbered a83, a82 and a81 in the PRs).

### #79
- `voicejobs.submit()` puts the job and checks the worker under `_lock`; `_loop` leaves on idle only under that lock, after re-checking `_q.empty()`, and resets `_worker`. Before, a job submitted while the idle worker was leaving stayed in the queue with no worker until the next one (the runner gave up after `VOICE_WAIT_S`). Test `test_job_submitted_while_the_idle_worker_leaves_is_still_run`.
- Sessions page, touch layout: `touchPicking` (blank screen while a session is picked) is off when `useSessions` failed with no data; the header (☰, ⋯) stays and an error `EmptyState` offers Retry (`refetch`). New i18n key `sessions.touch.loadError`. Before, a 500 on `/api/sessions` left a screen with no button at all.

### #81
- Mobile header (`Column.tsx` `ColumnHeader`, touch layout): 3 rows (☰ / logo + name / ⋯ / ⊞, title, `# topic ▾`
  + cost + `ContextGauge ring` from `Widgets.tsx`).
- Bottom-sheet menus on touch: `.mx-sheet` (globals.css) + `useMenuSheetDrag` (`components/ui/sheet-drag.ts`, drag
  down to close) in `dropdown-menu.tsx`, `select.tsx` (exit animation), `popover.tsx` (`sheet` prop), `combobox.tsx`.
- `Tree.tsx`: drawer toolbar (`toolbar`, `ListOptions side`) under the search on touch; `content-visibility` on
  `ProjectNode`. Settings sections slide (`mx-slide-x-r/l`), `TouchNav` help folds with an animation,
  `MobileOverlay` opens in a rAF, `Elapsed` isolated in `Thread.tsx`, no drawer shadow.
- Server: `_waiting_items` skips a `held` queue item (the user message kept at the head during an idle
  compaction): it was counted in `queue` / `queue_items` while the client already showed it as sent (duplicate).

### #82
- `gitview._gh`: GitHub 401 -> `GitError(502, "bad_token")` (was 401, which the UI took for a sign-out on every
  ```git block / git page with a revoked token).
- `web/src/lib/api.ts`: the global sign-out redirect fires only on 401 with `error: "auth_required"` (the server's
  own session check: `security.py`, `api/auth.py`, `bodylimit.py`, `uploads.py`, and `app.py`'s default for a bare
  401). Any other 401 (extension APIs, relayed upstream refusals) is a plain `ApiError`.

### Adapted at integration (wins over the notes above)
- #81: `_waiting_items` drops the head being sent (state `running`, no `pid`) **before** filtering `held` items.
  Filtering first made a runner restarting with the held message at the head drop the next waiting message too
  (count one short while the turn started). Test `test_held_head_while_a_turn_starts_hides_only_itself`.
- a80's #80 (Browser of my PC): `PcHub.channel()` sends the closing `{"t": "end"}` under
  `anyio.move_on_after(5, shield=True)`. A cancelled relay (local DevTools socket torn down, shutdown) skipped it,
  leaving the channel open on the PC; it also made `test_pc.py::test_agent_tunnel_and_tool_call` fail about one run
  in four ("timed out: channel end": Starlette's test client cancels the handler on close).
- Not changed: the extension UI kit (`ui-kit.css`) keeps anchored menus; `.mx-sheet` is the app's touch layout only.

## 2.0.0-alpha.80 - 2026-10-21

FEU's PRs #79 and #80 integrated (one commit per PR, without their version files; #80 was written on 2.0.0a77 and
numbered a79, #79 numbered a80).

### #79 - Radar fixes
- `gitview.github_name()` parses the remote (URL via `urlsplit`, or scp form `user@host:path`) and needs the host to
  be exactly `github.com` / `www.github.com`; `GH_REMOTE_RE` (unanchored search) is gone. Test
  `test_github_name_needs_github_com_itself`.
- `gitview.graph()` ends its `git log` call with `--`: selected refs can no longer be read as paths ("ambiguous
  argument" → 400). Test `test_graph_of_a_branch_named_like_a_file`.
- Telegram `gateway._unique()` reserves the attachment name by creating it empty (`O_CREAT | O_EXCL`, parents
  created); `Client.download` replaces the placeholder, `_download` removes it on failure. Test
  `test_same_name_downloads_at_once_get_two_files`.
- Telegram `format.inline()` returns the escaped text untouched beyond `INLINE_MAX` = 2000 characters (the lazy
  `(.+?)` patterns are quadratic); `_answer` calls `fmt.render` through `asyncio.to_thread`. Test
  `test_render_of_a_huge_line_full_of_markers_stays_fast`.
- `CopyButton` is `max-md:size-10 pointer-coarse:size-10`: 40 px touch target instead of 36 px.

### #80 - Browser of my PC (`pcbridge.py`, `api/pc.py`, `pc-agent/`)
- New router `/api/pc` (API.md "Browser of my PC"); public routes `/api/pc/pair` (pairing code), `/api/pc/download`,
  `/api/pc/install.*`, `WS /api/pc/ws` (device token); loopback-only + secret: `POST /api/pc/mcp`, `WS /api/pc/cdp`.
  `bodylimit._public` lists `/api/pc/pair` and `/api/pc/mcp`.
- State `<state>/pc/` (devices.json 0600, actions.jsonl, tools.json, bin/, tools/chrome-devtools-mcp-1.11.0/).
  Pairing registers the user-scope MCP `harness-pc` (type http, Bearer secret) through `mcp.add`; unpair removes it.
- `pc-agent/`: Go agent (Windows / macOS / Linux, amd64 + arm64), contract `pc-agent/PROTOCOL.md`, `build.sh` ->
  `dist/` + `SHA256SUMS` (reproducible). Binaries come from a release listed in `server/maxxing/pc_agent.json`
  (version, url template, sha256 per file); `MAXXING_PC_BIN_DIR` overrides it.
- `chrome-devtools-mcp` (npm, pinned 1.11.0, `--ignore-scripts`, bundled: no dependencies) is installed and spawned
  on the first tool call, one per server (lock), stopped after `idle_min`, on **Stop now**, on unpair and when the
  agent disconnects. `pageIdRouting` stays on. The agent opens `about:blank` at launch; on Linux the browser gets
  `Pdeathsig`.
- Security: a paired PC waits as `candidate` until `POST /api/pc/confirm`; the agent filters every DevTools command
  (`cdpfilter.go`); the server drops `filePath` / `sourcePath`, refuses non-page URLs, redacts logged URLs and caps
  channel queues (64 MB).
- `maxxing serve --port` exports `MAXXING_LISTEN_PORT`: local clients (`pcbridge.local_port()`) follow it.

### Adapted at integration (wins over the notes above)
- #80: `pc_agent.json` lists no file yet (no agent release exists): `PcStatus.available` (MAXXING_PC_BIN_DIR or a
  listed file) hides the card and stops its polling while false and no PC is paired; `POST /api/pc/pairing` answers
  `409 no_agent`, `POST /api/pc/mcp/register` without a PC `409 not_paired`. The CHANGELOG bullet says "prepared" and
  has no `[Show me]` (its target is hidden). **Before listing the first agent release**: host the binaries where
  every buyer's server can download them (the GitHub release URL of a private repository answers 404 to them) and
  harden `cdpfilter.go` against duplicate / case-variant JSON keys (Go's decoder matches `Method` to `method` and keeps
  the last duplicate: decode the method with exact keys and refuse duplicates).
- #80: `pcbridge.confirm()` / `unpair()` are coroutines: the files in `asyncio.to_thread`, the hub (the agent's
  websocket, chrome-devtools-mcp) on the server's loop. They used to run in a worker thread, where `_schedule()` fell
  back to `asyncio.run()`: a websocket of the main loop driven from another loop (unpair never reached the PC, the hub
  stayed online). Test `test_unpair_drives_the_agent_socket_on_the_server_loop`.
- #80: `Child.start()` stops the process when `initialize` / `tools/list` fail or time out (`START_TIMEOUT`), and
  `ensure_cdm()` kills npm on timeout (`NPM_TIMEOUT`): no stray node per failed call. node / npm get `_child_env()`
  (PATH, HOME, locale, proxy / CA variables) instead of the server's whole environment. Test
  `test_a_failed_start_kills_chrome_devtools_mcp_and_hides_the_server_env`.
- #80: `_bad_url()` refuses http(s) URLs of the PC itself or its local network (`_local_host()`: localhost, private /
  loopback / link-local / CGNAT IPs including the short, decimal and hex IPv4 forms read by `inet_aton`, IPv4-mapped
  IPv6, bare single-label names, `.local` `.lan` `.home` `.internal` `.home.arpa` `.localhost`...): the MCP is
  user-scope, so a prompt injection in any session could otherwise read the PC's router / NAS / local services
  through the browser. Page scripts (`evaluate_script`) can still issue requests; the browser's own protections apply.
  Tests `test_local_network_of_the_pc_is_refused`, `test_internet_pages_are_allowed`.
- #80: the candidate keeps the client address of `/api/pc/pair` (`ip`, shown in the card with the time): a pairing
  code seen by someone else is easier to tell apart. Test `test_the_waiting_pc_shows_where_it_connected_from`.
- #80: `pcbridge.local_host()` = the `bind` address when it is not 0.0.0.0 / loopback (Tailscale mode); `mcp_url()`,
  the DevTools URL of chrome-devtools-mcp and `_loopback()` use it. Test `test_tailscale_bind_is_the_local_address`.
- #80: `tools_call()` only restarts chrome-devtools-mcp and the browser when the child died; a tool's JSON-RPC error
  (bad argument) is returned as is. Test `test_a_tool_error_does_not_restart_the_browser`.
- #80: `ensure_cdm()` docstring corrected (no lockfile is written: npm checks the tarball integrity, the package has
  no dependencies). `pc-agent/winres/icon.png` (a copy of `web/public/icons/icon-512.png`) removed, `build.sh` points
  go-winres at the product logo. API.md `PcStatus` / `PcPairing` follow the code.
- Not changed: `/api/pc/mcp` keeps the 1 MB body cap before its loopback check (public cap is 64 KB); the
  `harness-pc` MCP's Bearer secret is blanked by the backup export, so after a restore on a new server the card's
  re-register button is needed.

## 2.0.0-alpha.79 - 2026-10-21

- `Items.tsx` `VoiceNote`: one bubble (user-message style) instead of `MediaPlayer` + transcript box: a mic / pause
  button driving a hidden `<audio preload="none">` (`fileRawUrl`, several recordings of a steered item play in a
  row) and the transcript / "Transcribing…" / error. New i18n keys `voice.listen`, `voice.pause`.

## 2.0.0-alpha.78 - 2026-10-21

- Voice messages sent directly (setting `voice.direct`, default true, also on existing installs). Web: the mic
  uploads the recording with `/api/uploads` (`voice-YYYYMMDD-HHMMSS.webm`) and posts `/messages` (or
  `POST /api/sessions`) with `voice: <path>`; optimistic `Pending.voice` bubble; a refused send puts the recording
  back in the composer as an attachment. `direct: false` = previous behaviour (`/api/voice/transcribe`, `auto_send`).
- Server: `sessions/voicejobs.py`. `send_message` / `create_session` take `voice_path` (`409 voice_off` when
  `voice.readiness()` fails); the queue item gets `voice: [{id, path}]` and meta `voice_jobs[id] = {state:
  pending|done|error, path, text, error, at}`. One worker thread in the server process transcribes
  (`voice.transcribe_file`, warm local model), first remuxing browser WebM in place (`-c copy`, adds the duration),
  and calls `titles.first_message` with the transcript. `resume()` at startup (`api/voice.startup`) relaunches
  pending jobs and drops the ones older than 24 h. Stop / Clear / Edit drop the jobs of the removed items;
  `take_queue` returns the transcript as text when ready, else the audio as an attachment; steer merges `voice`.
- Runner: a voice item writes `mx_user` with `voice:[path]` at once, polls meta `voice_jobs` (0.5 s, 30 min max,
  Stop ends the wait), then writes `mx_voice {text, error, stopped?}` (normalised `voice_text`, indexed by search)
  and sends the transcript with `VOICE_PREFACE` (item `preface`, after an idle-compaction seed). Nothing heard /
  error: error note, no Claude call, turn error. `last_user_message` returns the transcript (Telegram mirror).
- `queue_items[].voice`, `SendMessageBody.voice`, `CreateSessionBody.voice`; the web folds `voice_text` into the
  previous voice `user` item (`heard`). Settings → Voice: "Send voice messages right away" (auto-send only shown
  when it is off).

## 2.0.0-alpha.77 - 2026-10-21

- No page zoom on touch screens: viewport `maximum-scale=1, user-scalable=no`; `html` `touch-action: pan-x pan-y`
  (was `manipulation`); `lib/mobile-viewport.ts` `useNoPinchZoom()` (pointer coarse) cancels `gesturestart` /
  `gesturechange` and two-finger `touchmove` (non-passive) for iOS Safari tabs. Pages that want pinch must
  implement it themselves.
- Touch home: `useTouchHome` (AppShell) now decides at the first render (`useState` initializer) and renders
  `<Navigate to="/sessions" replace>` instead of `<Outlet>` - the dashboard is never drawn first (it flashed for
  ~100 ms). Sessions page, touch layout: header and empty state hidden while the session to show is picked
  (`touchPicking`), so `/sessions` goes from the splash straight to the session.

## 2.0.0-alpha.76 - 2026-10-21

Touch layout for phones and tablets. Web only, no API change.

- `html[data-compact]` = touch layout: `stores/media.ts` `isCompact(layout)` / `useCompact()` / `bindCompact()`
  (`main.tsx`), same rule inlined in `index.html` before the first paint: width < 768 px, or
  `(pointer: coarse) and (hover: none)` unless the device forces `desktop`; `touch` forces it. New persisted
  `useUI` fields `layout: 'auto' | 'touch' | 'desktop'` and `touchHome: 'session' | 'dashboard'` (`mx-ui`).
- `globals.css` redefines the Tailwind variants: `@custom-variant md (&:where(html:not([data-compact]) *, …))`,
  `max-md` on `html[data-compact]`. All existing `md:` / `max-md:` classes now follow the layout, not the width
  (tablets get the phone UI). Specificity unchanged (`:where`), `md:` keeps its place before `lg:` in the output.
  `useIsMobile` (both copies) = `useCompact`; `useIsTablet` = 768–1023 px window in the desktop layout;
  `sheet-drag.ts` uses `isCompact()`.
- `components/shell/TouchNav.tsx`: `useTouchNav` store (`panel: 'sessions' | 'app' | null`), `TouchSessionsButton`
  (☰, unread counter / running dot, `data-tour="touch-sessions"`), `TouchAppButton` (⊞, dot on pending update or
  health warn/error, `data-tour="nav"`), `TouchDrawers` (mounted by AppShell in the touch layout; closes on any
  location change; edge swipes in standalone mode; non-modal while the tour runs). The app drawer replaces
  `MobileMenuSheet`/`MorePages` (removed from `UserMenu.tsx`) and lists `useNav()`, `/feed` (unread count), `/x` +
  pinned pages, `UpdateIndicator`, `HealthSummary`, `UsageIndicator visible`, theme, presentation, settings, help,
  install, sign out.
- `components/ui/drawer.tsx`: Radix Dialog side drawer that stays a side panel on phones, horizontal swipe to close.
- `pages/sessions/SessionsPanel.tsx` (lazy, group `files`): `SessionTree touch` (new prop: `TouchHeader` with
  search, New session in the active topic, All/Running/Unread chips; view switches + New project in the footer).
  Rows `max-md:h-14` two lines (Favorites/Recent too), topic/project `max-md:h-12`, 15 px. Row menus: trigger
  `max-md:invisible` (kept as anchor), opened by `lib/long-press.ts` `useLongPress` (450 ms, 8 px slop, the
  following touchend is cancelled).
- Sessions page in the touch layout: no tree, `/sessions` without `session`/`new` redirects (replace) to the
  focused column or the most recent session; `?show=` opens the drawer. `MobileOverlay` loses its back gesture
  (`lib/edge-swipe.ts` removed) and its `role="dialog"`; the page header is not rendered under it. Column header
  `variant="mobile"`: ☰ … ⋯ ⊞; plan mode and Telegram notify move into the ⋯ menu (checkbox items). `onBack` props
  removed.
- AppShell: `MobileTabBar` removed (`--tabbar-h` gone, BulkBar/Tour/Board offsets updated), `Sidebar` not
  rendered in the touch layout, `useTouchHome` sends a fresh load of `/` to `/sessions` (setting `touchHome`).
- Composer: voice, send and stop buttons `max-md:size-11` round.
- Tour: drawer steps open/close panels via `before`; `sessionsList` returns null in the touch layout. Showcase
  `touch-nav`; `topic-permissions` opens the sessions drawer on touch.

## 2.0.0-alpha.75 - 2026-10-21

FEU's PR #78 integrated (Radar fixes; one commit without its version files; web/dist rebuilt).

### #78

#### perf
- `/api/dashboard`: `_defs()` keeps the resolved `Extension` on each extension widget (`_ext`, never sent) and
  `_compute` uses it, instead of `extensions.get()` per widget, which re-ran `_signature()` (iterdir + 3 stat
  per extension) each time: one scan per request instead of N widgets × N extensions (50 extensions: 155 → 23 ms
  median). Test `test_dashboard_scans_the_extensions_folder_once_per_request`.

#### responsive
- `Button` size `icon-sm` gets `pointer-coarse:size-10` (was `max-md:` only: 32 px on touch tablets ≥ 768 px);
  the % reset button of `textZoom.tsx` gets `pointer-coarse:h-10`.
- Session header on touch (`pointer-coarse:`): title row and path row `h-10`, the rename button and the move
  picker trigger `h-10` (were 20 / 17 px). `Thinking` toggle (Items.tsx): `before:` hit area 10 px above and below,
  no layout change.
- `Input`, `SelectTrigger` and `Button` size `icon` get `pointer-coarse:` next to `max-md:` (44 px on touch tablets
  too, were 36 px). Infra: text links and the "Connect {name}" pills `pointer-coarse:min-h-10`, per-resource project select and the overview
  "Hide" button 40 px on touch.
- Feed page: source filter chips `max-md:h-10 pointer-coarse:h-10` (were 36 px on phones, 28 px on touch tablets).
- `SecretInput`: the show/hide button `pointer-coarse:w-11` (was 40 px wide; its height follows `Input`, now 44 px).
- Settings navigation: phone pills `max-md:h-10 pointer-coarse:h-10`, sidebar rows and their sliding highlight
  `pointer-coarse:h-10` (the highlight offset is now `var(--row)`, 2.625rem on touch).

#### bug
- Reduced motion (`prefers-reduced-motion`): `animation-delay: 0ms !important` next to the 0.01 ms duration; the
  dashboard chart entrances (`mx-dot-in`, `mx-sweep`, `mx-grow-y`, `mx-draw`, `backwards` fill) kept their 120-720 ms
  delays and stayed invisible meanwhile.
- `claude_auth.record_limits` keeps only finite utilizations; `limits()` skips a window whose utilization is not a
  finite number, drops a non-finite `resets_at` and clamps `pct` to 0-100 (NaN / 1e999 in claude-limits.json made
  every GET /api/usage raise in the JSON encoder).
- Usage endpoint: the Retry-After deadline of a 429 is written to `STATE/claude-usage-block.json` and read back on the
  first reading after a restart (`health._restore_block`, capped at 2 h); it lived in memory only, so a restart called
  the endpoint again at once.
- `api/files._archive`: a listing cut by `ARCHIVE_TIME_S` is returned but not cached (the cache key is path + mtime +
  size, so one slow moment kept the list truncated until the file changed).
- Files API: a path sent back with U+FFFD (how `_shown` lists a name that is not UTF-8) is mapped by `resolve`
  (`_unshow`) to the one name of its folder shown that way, so read / move / delete work on it; `/move` destination
  and `/mkdir` keep the new name as typed (`resolve(new=True)`); `_entry`, `/list`, `/read` and `/archive` answers
  show their path with `_shown` too (the raw byte made them 500).
- File viewer: `readPos.validReadPos` checks every stored field (`view`, finite `frac`, integer `line` / `block.i` /
  `h.i`, finite `block.r` / `h.within`) and drops the entry otherwise; `textZoom` `apply()` restores a block only when
  it is an `Element` (`block.i: 'length'` threw in the requestAnimationFrame). Checked with `node
  --experimental-strip-types` (no web test runner).
- Infra RDAP: `rdap_expiry` keeps `eventDate` only when it is a short ISO date (else `error: bad_answer`) and the
  registrar only when it is a short string; `build._ts` turns NaN / inf into None (an `eventDate` NaN or 1e999 was
  saved in rdap.json and every Infra build then failed).
- `sessions.normalize.normalize_lines` skips a log line whose fields have an unexpected type (AttributeError /
  TypeError / ValueError from `normalize`), like it already skipped invalid JSON; one such line made reading the whole
  session fail.
- `sessions.service.move_session` checks again, inside `store.edit`, that no turn runs and nothing waits before
  changing `path` (the check read the meta outside the lock, so a turn starting in between kept running in the old
  folder while the session moved).
- `feedhooks.create` / `update` / `remove` run their read-modify-write of the sources list and of their secrets under
  one lock (`feedhooks._lock`); 12 sources created at once kept 1.
- `feed.post` replaces lone surrogates (valid in JSON as `\\ud800`) by `?` in title, body, url, dedupe and group
  (`feed._utf8`); SQLite raised UnicodeEncodeError, not FeedError, so the webhook answered 500 and the event was lost.
- `feedhooks.deliver`: a body nested deeper than `json.loads` can parse (RecursionError) answers 400 `bad_json`
  instead of 500.
- Stripe signature: the `t=` timestamp must be ASCII digits (`str.isdigit` accepts `²`, then `int()` raised: 500
  without knowing the secret); it is now a 401.
- `feedhooks.deliver`: a parser (Stripe / Shopify / GitHub) that meets a field of an unexpected shape (`data.object` a
  string, `pull_request.user` null, `commits` not objects) answers `400 bad_payload` (API.md) instead of an
  AttributeError (500).
- `crons.append_run` takes its flock on a stable `runs.jsonl.lock`, not on runs.jsonl itself: the trim replaces
  runs.jsonl (`os.replace`), so a writer waiting on the old inode appended to a file nobody read (8 processes x 40
  runs over a trim lost 10).
- Cron expressions: numbers and steps must be ASCII digits (`crons._value`, `_parse_field`); `str.isdigit` let `²`
  through to `int()` (ValueError, 500 on POST/PATCH /api/crons and preview) and accepted `٣`, then written to the
  crontab.
- Cron timeouts: `crons._clean` turns an OverflowError (`timeout_s` inf / 1e999 via create_job / update_job) into
  `CronError invalid_timeout`; `crons._timeout` reads `timeout_s` for the shell run, the Claude turn and
  `unit_properties` with a fallback to the default (`"30"` in a hand-edited jobs.json made `proc.wait` raise TypeError
  and left the job group running unbounded); `_run_shell` kills the process group on any exception from `wait`.
- `extensions.call` runs extension code through `_guarded`: a SystemExit / KeyboardInterrupt from `handle()` or
  `card()` becomes `RuntimeError("extension stopped (SystemExit)")`, like `_import` already did; it was re-raised by
  `await` in the event loop and passed every `except Exception`.
- `packs.install` runs under one lock (`_install_lock`): the free project name, the copy and the job names are chosen
  from what is on disk, and the API runs installs on threads (6 parallel installs of one pack all took the same
  project and doubled its jobs).
- Auth: `_check_strength` answers `400 bad_password` (API.md) for a password UTF-8 cannot encode (a lone surrogate,
  valid in JSON); `hash_password` raised UnicodeEncodeError, a 500 on /api/auth/setup and /api/auth/password (nothing
  was written).

### Adapted at integration (wins over the notes above)
- Feed webhooks: `deliver` turns the title / body / url a parser returns into text (`None` -> ""), and `_money`
  catches OverflowError: a signed Shopify body with `"email": 5`, a GitHub `html_url` that is a number (TypeError in
  `feed.post`'s URL check) or a 400-digit Stripe amount (`float()` OverflowError) still answered 500. Coerced rather
  than refused so a real event with a numeric field still reaches the feed. Test
  `test_webhook_fields_of_another_type_are_text_not_a_500`.
- Session header on touch: the path row stays `h-5` (the PR made it `h-10`: with the title row, the phone header grew
  by 24 px, after the a66 work to keep the mobile chrome short). The move picker trigger gets an invisible tap area
  instead (`before:` 6 px above, 12 px below: 38 px), the pattern the PR uses for the Thinking toggle. The title row
  keeps `pointer-coarse:h-10` (+4 px).

## 2.0.0-alpha.74 - 2026-10-20

FEU's PR #77 integrated (one commit without its version files; web/dist rebuilt). Nothing adapted at integration.

### #77
- `tasks.load(copy_=False)` returns the shared cache (read-only callers only); `GET /api/tasks` and `summary()`
  use it, writers still get a deepcopy. `sync_workspace()` returns before `load()` when the file signature and the
  workspace names match the last sync. `GET /api/tasks` returns a `JSONResponse` (skips `jsonable_encoder`).
  5000 tasks: list 288 -> 46 ms, summary 64 -> 0.8 ms. Test
  `test_tasks_safety::test_reading_the_tasks_does_not_copy_the_whole_file`.

## 2.0.0-alpha.73 - 2026-10-20

FEU's PR #76 integrated (one commit without its version files; web/dist rebuilt). Nothing adapted at integration.

### #76 - Radar fixes

#### bug
- `customs._find()` matches a commit prefix only from 4 characters and refuses an ambiguous one (`CustomError`);
  the exact id still wins. `drop("")` used to rebase the oldest customization away. Test
  `test_customs::test_drop_needs_a_real_id_not_an_empty_or_tiny_prefix`.
- `tasks._norm_task()` also catches `OverflowError` on `priority` (`1e999` = infinity) -> 0. Test
  `test_tasks_safety::test_a_huge_priority_does_not_break_the_task_page`.
- `tasks._num()` and `order` drop non-finite numbers (`1e999`, `"1e999"`, `NaN`, an integer too big for a float) for
  the default: they passed `load()` but the JSON answer failed. Test
  `test_tasks_safety::test_infinite_order_or_dates_do_not_break_the_task_page`.
- `tasks.load()` drops a project `workspace` that is not a string: `_sync()` keys a dict by it and a list raised
  `TypeError` on every GET. Test `test_tasks_safety::test_a_project_whose_workspace_is_not_text_does_not_break_the_task_page`.

#### security
- `customs.dirty_files()` reads `git status --porcelain -z`: paths come raw instead of C-quoted (`"web/caf\303\251 x.js"`
  no longer escapes the `startswith("web/")` checks of `save()` and `cmd_update`), renames/copies list both paths, and
  the text after the last NUL (stderr) is ignored. Test `test_customs::test_quoted_web_paths_are_still_refused`.

## 2.0.0-alpha.72 - 2026-10-20

FEU's PRs #61, #66, #70, #72, #73, #74, #75 integrated (one commit per PR without their version files; their own
numbers a72-a86 replaced by this one). #73 replaces #60, #62-#65, #67-#69, #71 (closed by FEU).

### #61 Git graph: open on GitHub
- `GitGraph` takes `github` ("owner/name") and `onGithub` (graph read from GitHub); a right click / 550 ms long press
  on a branch or remote label (`data-testid=git-branch-menu`) or on a commit row (`git-commit-menu`, only when the repo
  has a `github`) opens one shared menu; its handlers stop propagation so the chat message menu does not open too.
  `pushedShas()`: a clone's commit links to `/commit/<sha>` when an `origin/` ref leads to it in the loaded graph. `branchUrl()`: remote refs count
  only on `origin/` (the repo's `github` is origin's), a clone's local branch only when `origin/<name>` is among the
  loaded refs, every branch of a GitHub graph; segments URL-encoded, slashes kept. Tags get no menu. Used by
  `GitBlock` and `GitPage`. Showcase `git-branch-menu`. No server change.

### #66 Dashboard motion
- Dashboard motion (web only). `globals.css`: `.mx-grow-y`, `.mx-draw` (`pathLength="1"`), `.mx-sweep`,
  `.mx-dot-in` (`--i` lane, `--x` 0..100), `.mx-wait` (pauses a card's animations and its children's).
  `pages/dashboard/blocks.tsx`: `useCountUp` (numeric stat values, rAF, from 0 on first view / from the old value
  on change), `InView` context, `.mx-rise` on list rows, grid tiles and table rows, timeline lanes / tracks / dots /
  now line. `charts.tsx`: bars grow, line draws, area fades, last point pops. `ProgressBar` gets `grow`.
  `index.tsx`: `useWaitForView` (IntersectionObserver; none under reduced motion or when already on screen),
  `useGridFlip` (2-D FLIP of the cards on feed panel / visibility / order change, reset after edit mode),
  the update time re-fades on each refresh. Showcase `dashboard-motion`. No server change.

### #70 Plan usage bars, queue items
- `health.usage()`: the endpoint path moved to `_endpoint_usage(force, now)`; any reading without values (cached
  failure within 60 s, `blocked_until` after a 429, first failure) falls back to `claude_auth.limits()` when a turn
  ever saw limits. Before, both early returns under `_usage_lock` skipped that fallback, so `/api/usage` answered
  `available: false` for up to the whole Retry-After once the turn limits were older than `TURN_FRESH_S`, and
  `UsageIndicator` unmounted. Test `test_usage_from_an_old_turn_survives_a_rate_limited_endpoint`.
- Session gains `queue_items` (`service._queue_preview`, built on `_waiting_items`, same skip of the head while a
  turn is starting): `{text (280 chars), attachments: count, source, kind}` per waiting item. `Composer` gets
  `queueItems` and renders them when they cover the count (prefix `sessions.queue.from.<source>` for telegram /
  cron / system, `sessions.queue.files` when there is no text); the local `Pending` list stays the fallback (older
  server) and the source of `Edit`'s local seed. Before, the in-memory pending store was lost on reload, so the
  user's own queued message showed as `sessions.queue.other`. Tests in `test_sessions.py`; `useSetSessionCache` keeps the cached `queue_items` array while equal, so a running turn's ticks stay "ticking" (no tree re-render). Browser check `responsive-audit/queue-items.mjs`.

### #72 Settings side list
- Settings, desktop side nav (`pages/settings/index.tsx`): sticky without a height cap, so on a window shorter than
  the 17 sections its bottom was never reachable. It now has `max-h: 100dvh - header - 4rem - safe-bottom`,
  `overflow-y-auto overscroll-contain` (p-1/-m-1 so focus rings are not clipped), and the section effect scrolls the
  active item into the list (not the page). Browser check `responsive-audit/settings-nav.mjs` (1280x700, 1024x560,
  1440x1000).

### #73 Radar audit fixes
Radar audit fixes, one commit per finding, grouped in one release (they used to come as one PR per category).

#### Nest crossed bold/italic markers into valid Telegram HTML (was #60)
- `sessions/spawn.py` `unit_end_reason`: also recognizes "The kernel OOM killer killed some processes in this unit" and
  "killed by the OOM killer" (OOMPolicy=continue never logs "result 'oom-kill'"); `_OOM_MARKS`; test_sessions.py.
- `sessions/runner.py`: `_oom_kills()` reads `oom_kill` from the unit cgroup's `memory.events` before/after each
  attempt; rc -9/137 with a higher count sets `Attempt.oom` and `_record` reports `OOM_ERROR`; test_turn_signals.py.
- `crons.py` `_run_shell`: the `cat` draining a pipe held open by a background child is now waited for by a daemon
  thread (`cron-drain`), so it is reaped when it exits; test_crons.py `test_shell_job_drain_cat_is_reaped`.
- `security.set_password`: password hash, new cookie_key, revoked_sessions and device_key removal go in one write via
  the new `config.set_secrets` (`set_secret` now wraps it); a failure can no longer leave old cookies valid. test_auth.py.
- `security._issued_at` and `check_setup_token` compare bytes (`hmac.compare_digest` raised TypeError on non-ASCII
  str). test_auth.py.
- `security._cookie_key` and `twofactor._device_key` use `str(k).encode()`, matching `cookie_valid`. test_auth.py.
- `api/files._ffmpeg_thumb` encodes into a unique `<key>.<rand>.part.webp` (`-f webp`), `os.replace` into the cache
  only on success, temp removed in a finally (`_trim_thumbs` sweeps crash leftovers). test_files.py.
- Concurrent `_thumb` calls for one key never see a partial file: the temp-file-then-rename write of `_ffmpeg_thumb`
  covers it (no per-key lock, both encode, the last rename wins); regression test in test_files.py.
- `api/files`: new `_shown()` maps surrogate-escaped names to U+FFFD in `_scan_entry` (name, path) and `_search`;
  JSONResponse no longer raises UnicodeEncodeError. The search index refresh (`search.py`) is unchanged. test_files.py.
- `infra/providers.py` `rdap_expiry()`: parse errors give `{"error": "bad_answer"}`, vCard items checked (list, length
  > 3); `infra/dnsinfo.py` `_query()`: non-object bodies or a non-list `Answer` raise ValueError (cached as an error),
  records without string `data` dropped. test_infra.py.
- `infra/__init__.py`: `RDAP_RETRY_S` (1 h) and `_rdap_due()`; entries with `error` are retried after 1 h, others after
  `RDAP_EVERY_S`. `providers.rdap_expiry()`: HTTP 429/5xx give `error: unreachable`. test_infra.py.
- `workspace.move_to_trash()`: labels over 200 bytes become 180 bytes + "-<sha1[:10]>" (origin kept in the sidecar);
  `api/files._write()`: temp file prefix ".mx-" instead of ".<name>.". test_trash.py, test_files.py.
- `trash.py`: `_is_extra()` tells a sidecar / .sessions folder from a deleted "x.json" (which has "x.json.json");
  used by `_entries()` and `_item()`. test_trash.py.
- `videos._trim_cache()`: removes `*.part.mp4` older than `PART_STALE_S` (1 h) whose job is not running.
  test_videos.py.
- `telegram/gateway.py`: `_dispatch` runs `_voice` and media `_converse` in the background through a new
  `Gateway._lane` (one ordered task chain per session/topic, cleared in `stop()`); plain text stays inline while
  no lane is busy. test_telegram.py.
- `sessions/service.py`: new `end_offset(sid)` (last line boundary of the raw log, read backwards).
  `telegram/gateway.py` `_track` starts the status there instead of `read_events(sid, 0)`, which stops after
  READ_CHUNK (4 MB). test_telegram.py.
- `telegram/gateway.py` `_poll`: `offset.json` is written after each update instead of once per getUpdates batch.
  test_telegram.py.
- `telegram/format.py`: `inline()` passes the emphasis result through new `_nest()`, which closes and reopens crossed
  `<b>`/`<i>`/`<s>` tags so the HTML always nests. test_telegram.py.

#### Telegram link code compared as bytes (non-ASCII text from a stranger is refused, not a crash) (was #62)
- `providers.rdap_expiry` reads through `_rdap_get`: streamed body capped at `RDAP_MAX_BYTES` (1 MiB, Content-Length checked first), `RDAP_TOTAL_S` (15 s) total deadline, at most `RDAP_MAX_REDIRECTS` (3) redirects, https only; non-object JSON = unreachable. Test `test_rdap_lookup_is_capped_and_redirects_stay_on_https`.
- `api/extensions._own_file`: `page.js`, `widget.html` and `widget-frame` serve the resolved file only if it stays under the extension's folder (404 otherwise). `packs._copy_missing` skips a dangling link at the destination and a file whose resolved parent leaves `dst_root`. Tests `test_extension_files_linked_outside_their_folder_are_not_served`, `test_basics_never_writes_through_a_link`.
- `/ext/{id}/page.js`, `widget.html` and `widget-frame` answer 404 when the extension has an `error` (as `/api/ext` refuses it). Test `test_extension_in_error_serves_neither_page_nor_widget`.
- `-format_whitelist` on every ffmpeg/ffprobe run over user files: `api/files.IMAGE_FORMATS` (image demuxers + mov for AVIF/HEIC) for image thumbnails, `videos.VIDEO_FORMATS` (`mov,matroska,avi`) for video thumbnails, `videos.probe` and the encode. Excludes concat, hls, tty. Test `test_thumb_does_not_render_a_file_outside_the_root_through_ffconcat`.
- `twofactor.revoke_all` records `challenges_not_before` (epoch) in secrets.json; `check()` drops (410 expired) any challenge whose new `Challenge.created` is not after it, so a revoke from the CLI process reaches the server's in-memory challenges. Test `test_cli_password_or_forget_kills_approved_challenge` (real subprocess).
- `/api/files/site-url` answers 415 for anything but `.html`/`.htm`; the single-file branch of `filesite.site` also refuses a path under a dot folder (relative to the files root) or outside `ASSETS`. API.md updated. Test `test_single_file_site_token_never_serves_a_file_under_a_dot_folder`.
- `files._archive`: tar read in stream mode through `_Capped` (`ARCHIVE_READ_MAX` 256 MiB decompressed, `ARCHIVE_TIME_S` 3 s, then `truncated`); zip central directory parsed entry by entry by `_zip_directory` (zip64 end record, prepended data, UTF-8 flag) instead of `zipfile.ZipFile`; results cached per (path, mtime_ns, size), 32 entries. API.md updated. Test `test_archive_bombs_are_listed_within_bounds`.
- `gateway._try_link` compares the pending code as UTF-8 bytes (`hmac.compare_digest` raises TypeError on non-ASCII str). Test `test_non_ascii_link_code_from_stranger_is_refused_not_crashing`.

#### the hidden sidebar no longer polls plan usage on phones; web/dist rebuilt (was #63)
- `gateway.sync_threads_with` announces `workspace` only when a thread was created or deleted (the session watcher re-syncs on `workspace`: a loop every `SYNC_DEBOUNCE`). Test `test_sync_does_not_retrigger_itself` (bus bound to the loop as in app.py).
- `api/auth`: `revoke_cookie`, `set_password` (setup, change), `twofactor.set_on` and `forget_devices` go through `asyncio.to_thread` (flock up to `FLOCK_WAIT_S`, fsync, scrypt); `/setup` is serialized by `_SETUP_LOCK` now that it awaits. Test `test_logout_does_not_freeze_the_event_loop` (config lock held by another process).
- `stats.compute` uses `store.read_cached` (unchanged meta = no parse; the dict is shared and never mutated there; the token backfill still goes through `store.edit`). Test `test_stats_do_not_reparse_unchanged_sessions`.
- `api/extensions._kit`: `ui-kit.css` re-read only when its mtime/size change (it is inlined in every widget frame); `/ext/ui-kit.css` sends an `ETag` and answers 304 to `If-None-Match`. Test `test_ui_kit_is_read_once_and_revalidated_with_an_etag`.
- `api/sessions._sse`: a running session is polled every `POLL_RUNNING_S` (0.1 s) until `QUIET_AFTER_S` (3 s) without an events/state frame, then every `POLL_QUIET_S` (0.25 s); any frame brings the fast pace back. Test `test_quiet_running_session_is_polled_less_often`.
- `deps.verify(names, versions=)` takes the versions `status()` already found (doctor's `check_managed_deps` calls `status()` first: one round of `--version` subprocesses instead of two). Recorded files are hashed through `_known_sha`: cache `<state>/tools/deps-sha.json` (0600) keyed by inode, size, mtime and ctime, so any write, chmod or touch re-hashes. Test `test_verify_rehashes_only_changed_files_and_doctor_asks_versions_once`.
- `UsageIndicator`: `useUsage(enabled, poll)` only from the md breakpoint (`useIsMobile`); the sidebar is mounted but `hidden md:flex`. Checked with the mock server and headless Chromium: `/api/usage` requests at 390 px 1 -> 0, at 1280 px 1 -> 1. web/dist rebuilt.

#### backup configure and forget wait for a running backup instead of deleting its working copy (was #64)
- `mcp.build`: `shlex.split` `ValueError` (unbalanced quotes in `command` or `args`) now raises `McpError(400, "bad_command")` instead of a 500; covered in `test_mcp.py::test_validation`.
- `mcp.add`: keys flagged `expose=True` by `_expose_refs` are reset to `expose=False` when `claude mcp add-json` fails (any exception, re-raised); `test_mcp.py::test_failed_add_hides_the_keys_it_exposed`.
- `backup.LEAKS` "password": the `://`, digit and letter lookaheads are bounded (`{0,256}`, `{0,128}`) so a single long token no longer makes the scan quadratic (216 kB took 66 s); `test_backup.py::test_scanner_is_linear_on_a_crafted_token`.
- `backup.configure` (write part) and `backup.forget` take `_flock()`: during a run, configure returns `{ok:false, error}` and `DELETE /api/backup` answers `409 busy`, instead of `rmtree`-ing the working copy under git; `test_backup.py::test_configure_and_forget_wait_for_a_running_backup`.

#### version bump (was #65)
#### MCP: parsed `.claude.json` cached (`mcp.py`)
- `_read_cfg()` keeps the parsed file keyed by `(path, st_mtime_ns, st_size, st_ino)`; `servers()` (GET `/api/mcp`)
  and `export()` share that dict and must not mutate it. `_write_cfg()` asks for `_read_cfg(fresh=True)` (its own
  copy, never cached). Measured: 96 ms per call on a 14.5 MB file (3000 projects), once per change now.

#### phone-sized buttons on touch tablets (was #67)
- Hover-revealed controls (`opacity-0 group-hover:opacity-100`): `pointer-coarse:opacity-100` added next to every
  `max-md:opacity-100` (Items, FeedItems, Tree, Board, List, Listing, diagram) and to the two that had no touch
  fallback at all (Board selection circle + task menu, Hud copy button). Same pattern as Composer.tsx quote button.
- `ui-kit.css`: new `.ui-table-wrap` (`overflow-x: auto`); under 640 px a bare `.ui-table` becomes
  `display: block; overflow-x: auto` (a 4-column table overflowed `.mx-ext` at 360 px). Test
  `test_ui_kit_tables_scroll_instead_of_overflowing`; documented in the extension skill, DESIGN.md, user doc 13.
- GitPage: `break-all` on the repository path line and on the failing-repo keys. Mcp key/value editor: row
  `flex-wrap` under 400 px, key `w-full min-[400px]:w-2/5`, value `min-w-0`. Tour placement with the on-screen
  keyboard (visualViewport) not changed: the tour only focuses its own buttons, the keyboard never opens during it.
- Files Listing: the list grid (and its skeleton) gets `grid-cols-[minmax(0,1fr)]`; the implicit `auto` track grew to
  the longest name's min-content (897 px at 360 px), so `truncate` never applied and size + row menu went off screen.
- `CopyButton` (code-block.tsx): `pointer-coarse:size-9` on every copy button, `pointer-coarse:opacity-100` on the
  code-block one (was opacity 0 and 28×28 at 820 and 1024 px touch).
- `Segmented`: both sizes `max-md:h-9 pointer-coarse:h-9` (sm had no mobile size: Preview/Edit 40×28 on phones).
  File viewer toolbars (rich.tsx Reload/New tab/filters, viewers.tsx PDF buttons): `h-7 pointer-coarse:h-9`;
  breadcrumb "…" (files/index.tsx) `pointer-coarse:py-2`.
- `Button` sizes `default` / `sm`: `pointer-coarse:h-11` / `pointer-coarse:h-10` next to the `max-md:` ones (iPad
  portrait at 820 px: "Check" was 95×32). Icon sizes unchanged: dense rows pass their own `size-7` + touch sizes.

#### responsive: Git graph on touch screens
- `GitGraph`: row height `ROW_TOUCH` (40) when `(pointer: coarse)` matches (`useMediaQuery`), `ROW_MOUSE` (30)
  otherwise; the lane SVG follows the same height (rows were 30 px at 390 and 820 px touch).
- `GitGraph` ref badges: no more `min-w-0` on the badge; a name longer than 7 characters gets
  `min-w-[calc(7ch+30px)]`, a shorter one `shrink-0`, and the current branch is no longer `shrink-0` whatever its length
  (at 390 px the HEAD row's remote badges were squeezed to 14 px, name width 0).

#### the backup secret scanner catches PGP keys, JSON passwords, npm/HF/SendGrid tokens, URL logins and UTF-16 (was #68)
- `mcp._secret_args`: an argument is secret when it holds a token, a login in an address, a `--name=value` or
  `Name: value` whose name looks secret (`SECRET_NAME_RE`), the value after a secret flag (`--token`, `--api-key`;
  not `--no-…`), or a non-plain header after `-H`/`--header`. Used by `_public` (and the backup export).
  `_url_masked` also masks an address with a path segment of 24+ letters/digits (`TOKEN_SEGMENT_RE`).
- `mcp.export`: `_blank_secrets` also blanks a value holding a URL login (`_has_userinfo`, `${REF}` logins kept);
  args are blanked with `_secret_args` instead of `_has_literal` alone.
- `mcp._add_json` (used by `add` and `restore`): `claude mcp add-json` gets `_redacted(cfg)` (non-ref header/env
  values, secret args and URL logins/tokens blanked), then `_write_cfg` writes the real entry into `.claude.json`.
- `backup._apply` with `hold`: a path that the current `include` + `ALWAYS` does not match is written to
  `<trash>/outside/<rel>` instead, listed in `held.outside` (manifest, `held_lines`, feed notice); `release_held()`
  copies them in when the destination is still absent (`files` in its result). `_strip_hooks` takes out every
  `HELD_SETTINGS` key; `hooks-held.json` entries are now `{"settings": {key: value}}` (older entries = the hooks
  value, still released).
- `backup.LEAKS`: `private key` also matches `BEGIN PGP PRIVATE KEY BLOCK`; new kinds `npm token`, `Hugging Face
  token`, `SendGrid key`, `password in a URL` (6+ chars mixing letters and digits, not `${…}`/`<…>`); `password`
  accepts a quote around the label and the value (JSON). `scan_bytes` also scans the UTF-16 decoding of a blob with a
  BOM or mostly NULs.

#### the first page downloads only the core dictionary and its route's groups (was #69)
- Perf, web (Radar r8820e13f): dictionaries split by namespace at build time. New Vite plugin `i18nSplit`
  (`virtual:i18n/<lang>/<part>` chunks `_i18n-<lang>-<part>-*.js`, `virtual:i18n-loaders`); `src/i18n/groups.ts`
  lists the groups (settings, auth, infra, git, tasks, files, show), every other namespace is the core awaited by
  `main.tsx`. `i18n/index.ts`: `loadGroups`, `withGroups`; `translate` loads a missing group on demand and renders ''
  meanwhile. `routes.tsx` `page(load, groups)`; `routePreload` map is now `l: {lang: {part: file}}` and routes carry
  their groups. GitBlock / InfraBlock / file viewer / what's new wrapped with `withGroups`. French dictionary on a cold
  `/`: 34.6 kB -> 15.9 kB brotli. Test `test_web_first_load.py` (reads web/dist). `code-block` stays in the barrel
  (no dependency of its own: its chunk is shared utilities).

#### Git commit detail answers 200 with garbage for a tree, blob or tag id (was #71)
- `gitview.graph()`: `HEAD` is passed to `git log` only when `rev-parse --verify HEAD^{commit}` succeeds (git 2.53
  answers "unknown revision" for an unborn HEAD, which was a 400 `git_failed`); "unknown revision" is also treated as
  an empty history.
- `gitview.commit()`: the id is resolved with `rev-parse --verify <sha>^{commit}` (404 `no_commit` for a tree or blob;
  an annotated tag answers its commit) and the resolved full sha is shown; `SHA_RE` uses `\A...\Z` (a trailing
  newline no longer matches).

#### bug: Stats and plan usage
- `stats.py`: `_int`/`_float` read every counter of a meta or log (`tokens.*`, `turns`, `cost_usd`, `days.*`); a
  non-numeric or non-finite value counts as 0 instead of raising (`/api/stats/tokens` answered 500). Test
  `test_stats_survive_non_numeric_meta_values`.

- `health._window` / `_epoch`: a NaN or infinite `utilization` / `resets_at` from the usage endpoint becomes `None`
  (it stayed in the `_usage` cache and made `/api/usage` answer 500 until the next refresh). Test
  `test_map_usage_drops_non_finite_numbers`.

- `health.usage`: one endpoint call at a time; concurrent requests (even `force`) wait up to `USAGE_WAIT_S` for the
  call in flight (`_usage["inflight"]`, an Event set after the cache update) and share its answer. Five parallel
  refreshes used to make five calls to an endpoint that answers 429 for up to an hour. Test
  `test_parallel_forced_usage_makes_one_upstream_call`.

- `ConnectionBanner.tsx`: the "back" pill is hidden by its own effect on `state` instead of a timer inside the
  `status` effect, which a new `reconnecting` blip during those 2 s cancelled for good. No web test runner: replay
  of both effects with a simulated clock (reconnecting -> open -> short blip -> open: "hidden" after 2 s).

#### responsive: Tasks page and release notes on touch screens
- `List.SelectDot`, `Board.ColumnSelect` and the card select dot: on `pointer-coarse` the button is a 40 px hit area
  (negative margins keep the layout) and the dot is an inner span; the row's dot wrapper gets `mr-2.5` so its area
  ends where the done box's 12 px area starts (dots were 20x20 in the list and 24x24 on the board at 390 px).

- Tasks touch targets: card ⋯ (`Board`) `size-10` on phones and `pointer-coarse` (negative margins keep the header),
  project ⋯ and "manage projects" `pointer-coarse:size-10` with `opacity-100`, side list rows `pointer-coarse:h-10`,
  chips `h-10`; `Segmented` buttons `h-10` on phones and touch (were 32/24, 36/28 and 36 px at 390/820 px).
- `ProjectNav` mobile chips: a last 40 px gear button calls `onManage` (`ProjectsDialog`); the column's gear is
  `max-md:hidden`, so a phone could only open it from `TaskSheet`.
- Tasks page: below 400 px the view `Segmented` renders at the top of the body instead of in the `Page` actions
  (`max-[399px]:hidden` / `min-[400px]:hidden`); at 360 px the truncated `h1` had 42 px for 51 px of text.
- `showcases.SHOW_LINK_CLASS` (pill classes, `pointer-coarse:h-10`) and `showcaseLink(start, before?)` (the
  `Markdown` `onLink`) are shared by `WhatsNewDialog` and `UpdatesSection`, which now also runs `showLinks` on each
  body (its links were raw 60x17 anchors to `#show:<id>`).

### #74 Text zoom and reading position
- Text zoom + reading position (web only). `features/files/readPos.ts` (no React, also used by the CodeMirror
  chunk): `useTextZoom` (zustand persist `mx-text-zoom`, steps 75-250 %), `getReadPos`/`setReadPos` (per path,
  localStorage `mx-read-pos`, 100 newest, written 400 ms after the last scroll), `sourceHeadings` (ATX headings
  outside fences) and `headingAt`/`fromHeading`. `ReadPos` = `{view: 'src'|'md', frac, line?, block?, h?}`: the
  view that wrote it restores exactly (editor `line`, preview top-level block index + ratio), the other one maps
  through the heading index + progress to the next heading, else `frac`.
- `features/files/textZoom.tsx`: `TextZoomControl` (inline from `inlineFrom` px, a popover below; the Files page
  folds it under 1536 px because its toolbar shares the width with the list), `useCtrlWheelZoom` (non-passive
  wheel, ctrl/meta, 30 px of delta per step), `ZoomBox`, `zoomsText(kind, preview)` (not for CSV / HTML previews),
  `MarkdownReader` (scroller + CSS `zoom`; measures its anchor in a `useTextZoom.subscribe` callback, i.e. before
  React renders the new zoom, and puts it back in a layout effect; restores once the lazy markdown chunk replaced
  the skeleton). Used by `FileView` (`data-testid=md-preview` kept) and `PreviewBody`.
- `CodeEditor`: props `zoom` (font-size compartment, `&.cm-editor` so it wins over the base theme; the top line
  stays at the top) and `memory` (save on scroll after the first restore, restore when the text first arrives);
  an external value change keeps the scroll. Other editors (crons...) are unchanged (no props).
- Showcase `text-zoom`. Browser check `responsive-audit/text-zoom.mjs` (14 checks: zoom anchor, Ctrl + wheel
  without page zoom, Preview -> Edit same section, Edit -> Preview and reload same block, zoom kept, viewer, 1600 /
  1280 toolbars, phone popover).

### #75 Video player lists
#### Player: native picker colors (`features/files/MediaPlayer.tsx`)
- `PickButton`'s invisible `<select>` inherited the player's `text-white/90`; on desktop Chrome/Firefox the opened
  list takes the select/option colors, so options were white on a white list. The select and each `<option>` now get
  `bg-popover text-popover-foreground` (the select stays `opacity-0`; phones keep their own picker).
- Test: `responsive-audit/picker-colors.mjs` (contrast of every option in both themes; 26 failures on a71, 0 after).

### Adapted at integration (wins over the notes above)
- #73 rebased by FEU onto a71 with 9 more findings (stats, plan usage, connection pill, Tasks and release notes on touch screens). Its single-call `_usage["inflight"]` logic is merged into #70's `_endpoint_usage()` split: the waiting request returns the shared answer and `usage()` still falls back to the limits seen in a turn (one place, as #70 wrote it); the Git graph keeps #61's menu handlers and `data-ref` on the badges with #73's `fit()` widths and touch row height.
- Merge #61 x #73 in `GitGraph.tsx`: both kept (menu handlers + `data-ref` from #61, `fit()` / `rowH` /
  `useMediaQuery` from #73). Showcases of #61 and #66 both kept.
- #73 `workspace.move_to_trash`: the 180-byte cut decodes with `errors="ignore"` (fsdecode left lone surrogates when the
  cut fell inside a multi-byte character: the trash item id could not be encoded, 500 on `/api/trash`).
  `test_long_name_cut_inside_a_character_still_lists`.
- #73 `mcp._add_json`: when the real config cannot be written back (entry not found under the key the CLI used,
  empty `.claude.json`, write error), the server is removed again (`claude mcp remove`) and `McpError(500,
  "not_saved")` is raised (vault keys hidden again by `add`). Before, a server stayed with blanked secrets /
  `https://redacted.invalid/`, silently. `test_add_with_secrets_is_undone_when_the_config_cannot_be_completed`.
- #73 Telegram lanes: Telegram marks an update read on the next `getUpdates`, so a voice note / file handed to a
  background lane was lost if the process stopped before the lane ended (before #73 it ran inline, so a restart
  replayed it). `<state>/telegram/inflight.json` lists the running lanes' messages (`_inflight_add/_drop`; a cancelled
  lane keeps its entry); the next `_poll` (once per process, `_inflight_take`) tells the user in that thread to send
  it again. Not replayed: the lane may already have started the turn. The mark is dropped as soon as `send_message`
  returns, inside its worker thread (`_inflight_lock`): a stop that cancels the lane during that call no longer asks
  for a message the session already has. Tests `test_voice_cut_by_a_restart_is_asked_again`,
  `test_voice_already_handed_to_the_session_is_not_asked_again`, `test_finished_voice_leaves_nothing_in_flight`.
- #73 `tests/test_security.py`: the fake `id_ed25519` content is written as two strings joined, so no key-shaped
  literal reaches the history (the leak gate and the pre-push hook refuse `BEGIN … PRIVATE KEY`).
- #73 `sync_threads_with`: "workspace" is also announced when `session_threads` changed (rename, dropped link), not
  only on created/deleted; an idle sync stays quiet. `test_renamed_thread_is_announced_once`.
- #73 `providers._rdap_get`: deadline checked before each request and bounding its timeouts (3 redirects x 8 s could
  reach ~30 s). `test_rdap_deadline_is_checked_before_each_request`.
- #73 `IMAGE_FORMATS` + `apng` (animated PNG fell back to the original file). `test_thumbnail_of_an_animated_png`.
- #73 i18n `loadPart`: a failed chunk is retried 30 s later at the earliest (`failed`, `RETRY_MS`), not on every
  `translate()` call (one `import()` per render offline); `tDyn` treats `''` (group downloading) as missing.
- #73 `deps.verify(fresh=True)` for `maxxing deps verify` (explicit check, no sha cache); doctor keeps the cache.
- #66 `useGridFlip`: positions are `offsetLeft/Top/Width` inside the grid (getBoundingClientRect moved with the page
  scroll and with a running slide's transform), and a ResizeObserver on the grid and cards keeps the "before"
  positions true between two changes (a card growing with its data, a resized window).
- #61 commit rows (with `github`) and labels with a menu: `pointer-coarse:select-none [-webkit-touch-callout:none]`,
  so a long press on iOS opens our menu, not the text selection / callout.
- #70 `queue_items`: the last 20 (`QUEUE_PREVIEW_ITEMS`; sent with every session and live update), `Composer` uses
  them when they cover `min(count, 20)` (the older ones are the "+ n"); a `system` item of kind `compact` / `handoff`
  shows `sessions.queue.kind.*` instead of the internal summary prompt. `test_queue_preview_keeps_the_last_twenty`.
- Behaviour changes kept from #73 (security), listed in the upgrade note: an extension file that links outside its
  folder is no longer served (404); an extension in error serves neither page nor widget; a held restore keeps files
  outside the backup list aside (`maxxing backup release`); MCP URL logins / flag-passed secrets are blanked in the
  backup export.

## 2.0.0-alpha.71 - 2026-10-19

### Tasks: workspace projects (`api/tasks.py`)
- `TaskProject.workspace` (optional): the name of the workspace project it mirrors. `sync_workspace()` creates the
  missing linked projects on the first `GET /api/tasks` of the process (`_synced`) and on every workspace change
  (`on_workspace_change`, registered at startup): rename = same task project renamed + `topic_path` of its tasks
  rewritten; deleted workspace project = `workspace` dropped (free project, tasks kept). `system` is created with
  `hidden: true`. A task saved with a `topic_path` takes the project of that topic.
- `DELETE` of a linked project = `409 linked_project` (hide it instead). Unknown fields are still kept.
- Tests: `tests/test_tasks.py` (`wsclient` fixture); `_org_helpers.py` resets `_synced`.

### Front (`features/tasks/`)
- `ProjectNav.tsx` (left bar / chips), `Overview.tsx` (cards + `ProjectHeader`), `Week.tsx`, `Calendar.tsx`;
  `Board.tsx` generic (`BoardColumn`, `statusColumns`, `layout` grid|scroll, lanes); `List.tsx` groups by topic.
  Scope in the URL: `?project=<id|name|all|none|overview>`. `model.ts`: `projectStats`, `orderProjects`, `weekStart`.
- Showcase `tasks` (target `data-tour="tasks-projects"`).
- On an existing install the first GET adds one task project per workspace project (ours: 7).

## 2.0.0-alpha.70 - 2026-10-19

IMPORTANT release: audit 1 (server, F01-F18), audit 2 (fresh install on Ubuntu), a developer's remark ("third-party
scripts, curl everywhere, no management of external dependencies, the system does not clean up after itself") and
our installer reviews, in one version. Commits by theme: installer security, managed
dependencies, installer reliability, web service memory cap, crons units (F07/F08), unit hardening (F02), default
jobs, skill paths, request size (F01), previews (F03/F16), restored extensions (F04), SSE auth (F05), Infra checks
(F17), Garage sha256 (F18), Python floor (F14), SSE caps (F01).

### Managed dependencies (`deps.toml`, `deps.py`, `cmd_deps.py`)
- `server/maxxing/deps.toml`: one table per component (`uv python node claude caddy scrapling chromium remotion whisper
  garage`) with `title kind version url arch sha256 path links remove update owner osv lock source`; key reference in
  its header. Garage takes `version/url/sha256` from `infra/actions.py` (`GARAGE_VERSION`, `GARAGE_URL`,
  `GARAGE_SHA256`, F18: one source of truth), merged by `deps.load()`. install.sh reads the same file with a tiny
  reader (`dep NAME KEY [SUB]`: `[name]`, `k = "s"`, `k = ["a"]`, `k = { a = "b" }` on one line; tested equal to
  tomllib for every value), so the subset must stay that simple.
- `deps.fetch_verified(url, sha, dest)`: https only, streamed into `dest.part`, sha256 compared, then renamed; a
  mismatch deletes it. `work_dir()` = `mkdtemp` under `<state>/tmp` (0700, removed); `_run` gives every child
  `TMPDIR=<state>/tmp` (uv, npm, node compile cache no longer write to `/tmp`).
- Layout: Node.js in `<state>/tools/nodejs/<version>` + `current` link, `/usr/local/bin/{node,npm,npx,corepack}` link
  to `current/bin/*` only when free, already ours, or left by an older installer (install-manifest `node <prefix>`;
  that old extraction is removed - `NODE_LEGACY_PARTS` - and the manifest line dropped). Scrapling in a venv
  `<state>/tools/scrapling/<version>-<lock sha12>` + `current`, installed with `uv venv` + `uv pip install
  --require-hashes -r templates/scrapling/requirements.txt` (generated by `uv pip compile --universal
  --generate-hashes`), wrappers `/usr/local/bin/scrapling{,-python}` point to `current`. The old `tools/uv`,
  `tools/bin`, `tools/node` go once the new one runs. Python: `UV_PYTHON_INSTALL_DIR=<state>/tools/python`,
  `UV_PYTHON_PREFERENCE=only-managed`; `deps update python` moves the server venv onto it (`uv sync --python
  <managed>`, import check; the venv is copied to `.venv.pre-python` first and that exact copy is put back on
  failure, so a half-recreated venv never stays). Chromium: the revision(s) of the
  `playwright`/`patchright` drivers of the Scrapling venv (`driver/package/browsers.json`), `python -m <driver>
  install --no-shell chromium` into `<state>/tools/browsers`, `ldd` check then `install-deps` fallback. Remotion:
  `npm ci` of the template into `tools/remotion.new`, version check, swapped with `os.replace`. Whisper: models
  downloaded at the revision of `deps.toml` (`voice.download_model` passes `revision=`). Claude Code: only when
  missing, the pinned binary then `claude install <version>` (what Anthropic's install.sh does), `update = "self"`.
- `<state>/tools/deps.json` (0600): what was installed and the sha256 of the binaries (`verify` compares them).
- `verify()`: owner of every file of a component = root and not group/other-writable (non-executable `*.lock` files
  and sticky dirs aside; this generalizes the a68 Node.js uid-1000 check), recorded sha256, Garage pinned sha256,
  Caddy keyring fingerprint, Remotion lockfile hash. `status()` rows: `ok | outdated | missing | not installed`.
- `update(names)`: order `uv python node claude scrapling chromium remotion whisper garage`; each failure is
  reported, never raised, the others go on. `remove(name)` refuses `uv python claude caddy` without `force`.
  `clean()`: uv / npm / npx / pip caches, Claude Code downloads, old versions next to `current`, unused managed
  Pythons, browsers no driver needs and the headless shell / Remotion's own browser of older installs, leftovers of
  interrupted runs, `<state>/tmp` entries older than a day, `install-failed-*` logs older than 30 days, logs over 5 MB
  cut to their last 1 MB. `check()`: `depcheck.osv_scan()` + the Scrapling lock + the installed versions of the
  components with an `osv` key; `notify_vulnerable()` posts a feed event (dedupe on the advisory set) and the
  Telegram alerts thread only for a new set.
- CLI `maxxing deps list|verify|update|remove|clean|check [names] [--json --quiet --notify --dry-run --force]`
  (exit 1 when something is missing / fails). `python -m maxxing` now exits with the command's code (`__main__`).
- `maxxing update`: after the new code's `init`, `deps update uv python` (before the restart); after a healthy
  restart, `deps update --notify` in a transient unit `maxxing-deps-update-<ts>` (MemoryMax 2G, log
  `<state>/logs/deps-update.log`). Skipped under `MAXXING_SPAWN=direct`.
- Doctor `deps_files` (replaces `node_owner`): FAIL on a verification failure, WARN when a component is missing or
  not at the release's version. `uv_bin()` prefers `/usr/local/bin/uv`. Default jobs `deps-clean` (Sun 04:30,
  `deps clean --quiet`, notify failure) and `deps-check` (Mon 10:00, `deps check --notify`, notify never), created
  once like the others (existing installs get them at their next `init`).
- Uninstall: always the `/usr/local/bin` wrappers/links of ours and our fail2ban jail; with `--purge` also every
  component (uv and Claude Code only when the installer or `deps` installed them: install-manifest `uv installed` /
  `claude installed` or `deps.json`), Caddy + its key/source/admin drop-in when the manifest says `caddy installed`,
  and the swap file of `swapfile <path>`. Garage is kept (it holds the buckets).
- One Chromium: `templates/remotion/remotion.config.js` sets `Config.setBrowserExecutable()` to the Playwright
  Chromium found from `realpath(node_modules)/../../browsers` (+ `chromeMode` `chrome-for-testing`);
  `cmd_video.browser()` (PDFs) prefers it; `npx remotion browser ensure` is gone. Sessions' PATH gets
  `<state>/tools/nodejs/current/bin`. `hatchling==1.32.4` pinned in `pyproject.toml` (F09).
- `scripts/bump-pins.sh` now edits deps.toml in place (`pin SECTION KEY VALUE [SUB]`): uv (release `sha256.sum`),
  Node.js (GOODSIG from nodejs/release-keys), Claude Code (`stable` + its `manifest.json` checksums), Caddy key
  (reported, never rewritten), Scrapling + re-resolved hash lock; Remotion and Garage are reported only.

### Installer (install.sh)
- Order: packages -> code -> background download of Claude Code -> uv -> venv -> Claude Code -> init -> restore ->
  access -> security -> service -> tools (`maxxing deps update` in the transient unit `maxxing-deps-install`, log
  `<state>/logs/deps-install.log`; `TOOLS=foreground` waits, `TOOLS=0` skips; `--tools` = foreground).
- `fetch_verified URL SHA256 DEST` is the only download path (release archive included); `dep_fetch NAME DEST` takes
  url + sha of this machine from deps.toml. The pins at the top of install.sh are gone; Caddy's key URL, fingerprint,
  keyring and source line come from deps.toml, and only Caddy's list is refreshed for its install. `TMPDIR=$WORK`;
  `on_exit` removes the `mktemp` folder it created (`WORK0`) only.
- `install_packages`: one `apt-get update` + one `apt-get install --no-install-recommends` (retried with recommends)
  of `BASE_PKGS` (git curl ca-certificates cron openssl python3 gnupg openssh-client xz-utils tzdata), tools, security
  packages (unattended-upgrades fail2ban python3-systemd, ufw when it will be used) and the browser libraries (`a:b`
  = first name the release knows, `*t64` on 24.04+); skipped entirely when everything is installed (dpkg-query).
  `ubuntu_universe` adds `universe` to `ubuntu.sources` Components (or `add-apt-repository`) when no source has it.
- `ensure_swap`: 2 GB `/swapfile` (fallocate, else dd) when MemTotal < 4096 MB, no swap, not a container, 6 GB free;
  fstab line, manifest `swapfile /swapfile`; `SWAP=0`. `voice_memory_check`: under `VOICE_MIN_MB` (2800 MB) the
  default VOICE becomes off; an explicit `VOICE=local` is asked (default no) or refused unattended.
- `SOURCE_DIR` / `local_source` (the folder of the running script when it holds `server/maxxing/__init__.py` and is
  not `INSTALL_DIR`) -> `LOCAL=1` when there is neither LICENSE nor GH_TOKEN; `fetch_local` copies the tree (git
  `ls-files -co --exclude-standard`, else tar without `.git`, `.venv`, `node_modules`, `__pycache__`), requires
  `web/dist/index.html`, commits it in a repo without remote; a re-run with a newer copy replaces the tracked files
  when the tree is clean. An existing install without `origin` and without a license is `LOCAL=1` too.
- `setup_python`: `/usr/local/bin/uv sync --python <deps python.version>` with the managed-Python variables.
  `install_claude` uses `$HOME` (no `HOME=/root`), links `/usr/local/bin/claude`, manifest `claude installed`.
- Unit: `unit_text` with `MemoryMax=<60 % of MemTotal, at least 1024M>` (F01); `maxxing init` adds
  `claude-maxxing.service.d/20-memory.conf` (`MemoryMax=60%`) to a unit without MemoryMax (`ensure_service_memory`,
  removed by uninstall and by install.sh when it rewrites the unit).
- Inputs: `TIMEZONE` (`valid_tz_name`), `SOURCE_DIR` (`safe_path`), `TOOLS`, `SWAP` validated in `check_inputs`. On a
  re-run, Harness's own `~/.claude` no longer counts as "Claude Code already used". `| grep -q` after a long producer
  replaced by `| grep ... >/dev/null` (pipefail + SIGPIPE made `auto_upgrades_on` fail at random on Ubuntu 22.04).
- Removed: `install_tools`, `install_scrapling`, `install_node`, `node_tarball`, `node_owner_fix`, `uv_tarball`,
  the background `voice download` (the model comes with `deps update`).

### Installer security
First-run and license security (14e3ec6c):
- `security.SETUP_TOKEN_TTL` = 3600: `ensure_setup_token()` stores `setup_token_at`, `check_setup_token()` refuses an
  older token, `maxxing setup-link` mints a fresh one; `maxxing serve` never prints the link (journal), install.sh
  keeps `maxxing init`'s output in a 0600 log removed after the banner.
- `backup.restore(..., hold=True)` (install.sh `--hold`, and on a server in use): jobs created off, extensions in
  `extensions.disabled`, Claude Code hooks and local MCP servers kept in `<state>/backup/held.json`; `maxxing backup
  held` / `release`; `maxxing custom restore --stat` shows the saved product patches without applying them.
  install.sh asks (`RESTORE_TRUST=1` to accept unattended).
- `license.PUBKEYS` by key id (`k1`), a release's `kid` selects its key, an unknown id is refused (same list in
  install.sh `RELEASE_KIDS` / `RELEASE_PUBKEY_<kid>`, tested equal). `machine_id` sent to `/v1/update`, `/v1/ping`,
  `/v1/release`; a rotated token in a response is stored (`_rotate`). `is_downgrade()`: `fetch_latest` and
  install.sh (`MIN_VERSION`, `__version__` inside the archive must equal the signed one) refuse an older version;
  `maxxing update --allow-downgrade`. `LICENSE_API` must be https (http only to 127.0.0.1/localhost for tests).
- install.sh: `umask 077`, `cd /`, root's HOME/PATH (`reset_env`), dangerous variables unset, secrets `export -n`, the
  GitHub token through `GIT_CONFIG_*` env (F10), the license key on stdin; `secure_server` checks what it turned on
  for real (`auto_upgrades_on`, `fail2ban-client status sshd`, `ufw status`) and dies unless `ALLOW_UNPROTECTED=1`
  (F06); fail2ban jail `port =` the real SSH ports (F11); ufw add mode keeps existing SSH rules, Tailscale only gets
  the app port + SSH; `tunnel_cmd` uses `SSH_CONNECTION` user/address/port (F13); Caddy admin API on
  `unix//run/caddy/admin.sock` when the Caddyfile is ours.

install.sh, SSH by key only (`secure_server` -> `ssh_key_only`, plan in `ssh_plan`):
- `SSH_HARDEN=auto|1|0`. `ssh_plan` -> `done` (`sshd -T`: password + kbd-interactive already `no`), `skip:<why>`
  (SSH_HARDEN=0, no sshd, `sshd_config` without `Include ...sshd_config.d/*.conf`, no key in `authorized_keys` of
  root or a sudo/admin member) or `apply`: auto requires `ssh_session_uses_key` = the `SSH_CONNECTION` of this
  session (env, else an ancestor's `/proc/<pid>/environ`, for `sudo -i`) matches an `Accepted publickey ... from
  <ip> port <port>` line (journal `-t sshd -t sshd-session` 60 days, else `/var/log/auth.log`); `1` skips that proof.
- Drop-in `01-harness-maxxing.conf` (first match wins, before `50-cloud-init.conf`): `PasswordAuthentication no`,
  `KbdInteractiveAuthentication no`, `PermitRootLogin prohibit-password` only when the effective value is `yes`.
  Removed again when `sshd -t` fails or `sshd -T` still shows a password method; reload of `ssh`/`sshd` when active
  (socket-activated sshd reads it on the next login); manifest `ssh key-only` (uninstall prints how to undo, never
  re-enables passwords).
- Interactive installs ask (default yes) when the plan is `apply`; `--check` / preflight shows the plan.
- Pipelines in these helpers never use `grep -q` after a producer (`pipefail` + SIGPIPE gave false negatives).

### Scheduled jobs, unit hardening, default jobs, skill paths
- F07 / F08 (030c08f3): managed crontab lines are now `<schedule> [MAXXING_STATE=…] <maxxing> cron run <id>
  [--if-due] --detach`. `crons.spawn_run(id)` (Run now and `--detach`) starts `python -m maxxing cron run <id>` in
  `systemd-run --collect --unit maxxing-cron-<id> --slice=maxxing-jobs.slice` + `memory_properties()` +
  `RuntimeMaxSec=<timeout_s + KILL_GRACE_S + 120>`; inside, `run_job` keeps the per-job flock (a second start while
  the unit exists -> `already_running`, exit 3). New `maxxing-jobs.slice` written by `cmd_core.ensure_jobs_slice()`
  (every `maxxing init`, so every update; only when the text changed, then daemon-reload; removed by uninstall) with
  `MemoryMax=<jobs_memory_max>` (new config key, default `"75%"`, `""`/`"infinity"` = none). Timeout `_kill_group`:
  SIGTERM to the process group, SIGKILL to the whole group after `KILL_GRACE_S` = 5 s unconditionally, early exit
  when bash is reaped and the group is empty. Without systemd (`units_available()` false, or MAXXING_SPAWN=direct)
  `--detach` runs inline in the cron process (timeout still applies, memory caps do not).
  Tests failing on origin/main: `tests/test_cron_units.py` (timeout kills a child ignoring SIGTERM, crontab lines
  start the job in its unit, scheduled run goes through a job unit with memory caps, Run now uses the same unit,
  detach without systemd, init writes the jobs slice); `test_crons.py` / `test_cmd_core.py` adjusted.
- F02 hardening (02c726b4): `sessions/spawn.py UNIT_HARDENING` = `ProtectClock=yes`, `LockPersonality=yes`,
  `RestrictRealtime=yes` added to turn units and job units through `hardening_properties()`; config
  `unit_hardening` (default true). Rejected options and why are listed in docs/dev/INTERNALS.md "Unit hardening"
  (NoNewPrivileges breaks sudo/snap, ProtectKernel* breaks sysctl/modprobe/dmesg, ProtectControlGroups hides mounts,
  RestrictSUIDSGID breaks dpkg...). Tests failing on origin/main: `tests/test_unit_hardening.py`.
- Jobs (944f0963): `COMPACTION_JOB` is created with `enabled: False`; its id is stored in install.json
  `enable_after_onboarding`; `cmd_core.enable_pending_jobs()` is called by POST /api/onboarding/complete when
  `auth_status().ok`, enables the job only if the user has not changed it (`created == updated`), clears the list;
  the response gains `jobs_enabled`. Existing installs have no pending entry (their job is untouched). `update_source()`
  = "license" | "git" | None; None -> "Check for updates" created disabled, `update --check` exits 0 with "updates
  unavailable (no license, no remote)", `check_update` returns `{ok: true, git: false, ...}`. Doctor `memory` check:
  WARN under `SMALL_RAM_MB` = 4096 with less than 512 MB of swap. Tests failing on origin/main:
  `test_cmd_core.py::test_compaction_job_waits_for_claude_and_upgrades_keep_theirs`,
  `test_no_license_no_remote_means_no_failing_update_job`, plus a memory check case in `test_depcheck.py`;
  `test_claude.py::test_onboarding` expects the new `jobs_enabled` field.
- Skills (547164e4): `cmd_core.install_skills()` renders the `.md`/`.json`/`.txt` files of each copied skill with
  `template_vars(config.workspace())`; `template_vars` gains `{{STATE_DIR}}` (= `config.STATE`), also available to
  the workspace templates. `skills_status()` compares the installed SKILL.md with the rendered source (doctor
  `skills` check stays ok; a copy with stale paths shows "outdated", fixed by `maxxing init`). Skills edited:
  maxxing-setup, maxxing-doctor, maxxing-tasks, maxxing-cron, maxxing-customize, maxxing-extension, maxxing-feed,
  memory. Contributor rule: shipped skills use `{{CODE_DIR}}`, `{{WORKSPACE}}`, `{{STATE_DIR}}`, never the default
  paths. Tests failing on origin/main: `test_cmd_core.py::test_skills_are_rendered_with_the_paths_of_this_install`,
  `test_shipped_skills_use_placeholders_not_default_paths`.
- Docs touched in this branch: docs/dev/INTERNALS.md, docs/dev/API.md (onboarding/complete `jobs_enabled`),
  docs/user/05-memory.md, 08-crons.md, 14-skills.md, 15-security.md, 16-troubleshooting.md, 17-cli-reference.md.

### Server (audit 1)
- F01 `maxxing/bodylimit.py` (`BodyLimit`, ASGI, outermost after the security headers): every non-multipart
  POST/PUT/PATCH/DELETE under /api/ is decided from its headers before the body is read. No valid cookie on a
  non-public route -> `401 auth_required` before a byte is read; public `/api/auth/*` -> CSRF header first (`403
  csrf`), then 64 kB (`PUBLIC_MAX`); `/api/hooks/{token}` -> 1 MB (`feedhooks.MAX_BODY`); signed in -> 1 MB
  (`DEFAULT_MAX`) or the route cap (`ROUTES`: `PUT /api/files/write` 16 MB; `POST /api/sessions`, `/messages`,
  `/steer`, `/ask` 8 MB; `/api/ext/*` 5 MB). `Content-Length` over the cap -> `413 {"error":"too_large"}` with
  `Connection: close`; a chunked body is counted while it streams. Multipart stays with `uploads.UploadGuard`.
  Behavior change: a route whose JSON body grows past 1 MB needs a `ROUTES` entry (extension pages: 5 MB).
- F01 stream counter `maxxing/streamcap.py`: `/api/stream` and `/api/sessions/{id}/stream` answer through
  `stream_response(cookie, factory)`; a slot per sign-in (`security.session_id`) is taken before the body generator
  is created: `PER_SIGNIN` 24, `TOTAL` 96 (both kinds of stream together), else `429 {"error":"too_many_streams"}` +
  `Retry-After: 5` (the UI's `lib/sse.ts` already retries with backoff on HTTP errors: no web change).
  `CappedStream.__call__` releases the slot however the response ends (also when the client left before the body
  generator started), `weakref.finalize` if the response is never sent; release is idempotent.
- F03 `api/filesite.py`: folder tokens serve static web assets only (`ASSETS` = `html htm css js mjs wasm`, fonts
  `woff woff2 ttf otf eot`, pictures, audio, video). Removed from the list: `json jsonld geojson webmanifest csv tsv
  txt xml md pdf map glb gltf bin` (403 `forbidden`). From a topic's `attachments/`: pictures and media only. Too
  broad a folder (files root, home, `/`, under a dot folder, workspace root, `projects/`, a project or its `topics/`,
  a topic's uploads) -> the HTML file alone, as before. Behavior change: an HTML preview that fetched a `.json` /
  `.csv` / `.md` next to it gets 403 for it. Decision (coordinator, 19/10): an HTML preview does NOT open only its own
  file; it still loads the static web assets of its folder tree, and no data or document files. This was chosen
  over the plan's "own file only + explicit published folder" because it breaks fewer existing pages.
- F16 `api/filesite.py`: preview tokens carry `i` (issue time) and `s` (session id); `read_token` refuses them when `s`
  is revoked, when `i < sessions_not_before` (sign out everywhere, revocation list overflow) and after a password
  change (new `cookie_key`). Tokens without `i` (minted before a69) are refused.
- F04 `backup.py` + `extensions.py`: a restore on a server in use adds the ids of the extensions whose code files
  (`.py .js .mjs .html .htm`) it will write to config `extensions.disabled` BEFORE writing any file, all inside
  `extensions.publishing()` (thread RLock + flock on `<state>/extensions.lock`, also held by `scan()` /
  `set_enabled()` while they check the flag and import), so the CLI restore and the server exclude each other; a
  restored `extensions` setting keeps them disabled.
- F05 `security.StreamAuth(cookie).ok()`: `/api/stream` (`bus.stream(cookie)`) and `/api/sessions/{id}/stream`
  (`api/sessions._sse`) re-check their cookie before each frame: one stat of secrets.json while its (inode, mtime,
  size) is unchanged, a full `cookie_valid` when it changes, every `RECHECK_S` (15 s) and past the cookie's expiry;
  the stream ends when the check fails (sign out, revocation, `sessions_not_before`, password change, expiry).
- F17 `infra.check_url`: `httpx` streaming request closed after the status line and headers (the body is never
  read; h11 caps the header block at 16 KiB); a watchdog (`threading.Timer`, `CHECK_TOTAL_S` = 10 s) shuts the socket
  down (socket taken from the httpx `trace` extension, plain then TLS), since httpx timeouts are per read. Past the
  deadline the result is `down` / `timeout`. Results and the 16-thread pool are unchanged.
- F18 `infra/actions.py`: `GARAGE_SHA256` per architecture (x86_64 `543b0414…02839d8`, aarch64 `65a1bedc…ab278e8055f`
  for v2.1.0). Garage publishes no checksum: the values were taken from `GARAGE_URL` and cross-checked against the
  `garage` binary of the official Docker image `dxflrs/garage:v2.1.0` (both match; sizes match `_releases.json`).
  The download is hashed while it streams into `garage.part` (0700, `O_EXCL`); mismatch -> `ActionError` code
  `checksum_mismatch`, the part file removed, nothing installed. An already present `/usr/local/bin/garage` is not
  re-checked. Bumping `GARAGE_VERSION` now requires new hashes.
- F14 `pyproject.toml` `requires-python = ">=3.11"` (uv.lock relocked with uv 0.8.22 to keep `revision = 3`: only
  the 3.10-only entries left the lock - av 17.1.0, backports-asyncio-runner, exceptiongroup, mpmath, numpy 2.2.6,
  onnxruntime 1.24.3, sympy, tomli, websockets 16.1.1; no version changed). `cmd_core.PYTHON_MIN = (3, 11)`:
  doctor check `python` is FAIL below it (was 3.10). Repo CLAUDE.md and docs/dev/PLAN.md say 3.11.

### Adapted at integration (wins over the notes above)
FEU's PR #59 integrated as one commit (version files and web/dist rebuilt here), then adapted after a review against
a busy existing server (ours: other tools use its Node, uv caches, root crontab):
- `deps._may_link`: a free `/usr/local/bin/<x>` is linked only when no other `<x>` is on the standard PATH
  (`deps.SYSTEM_PATH`): the link shadowed `/usr/bin/node` for every program of the server, and `npm -g` then
  installed into a versioned folder the next Node update deletes. Harness still uses its copy (`node_bin()`).
- `deps._up_uv`: a `/usr/local/bin/uv` that is not ours (not in deps.json nor "uv installed" in the manifest) is kept
  unless asked by name (`explicit`); install.sh does the same (it was replaced, possibly downgraded, then removed by
  `uninstall --purge`).
- `deps._up_python`: `maxxing update` runs `deps update uv python --auto` (new flag, `explicit=False`): a working
  venv on a Python >= 3.11 (`PYTHON_FLOOR`) stays where it is - rebuilding it in place broke `/usr/local/bin/maxxing`,
  the crontab lines and new turns for minutes while the service ran. `maxxing deps update python` still moves it.
- `deps.clean(caches=False)`: root's `~/.cache/uv`, `~/.npm/_cacache`, `~/.cache/pip`, `~/.npm/_npx`,
  `~/.claude/downloads` only with `--caches` (shared with every tool of the server; MCP servers run from `_npx`).
- `ensure_default_crons`: on an install that already had default jobs, `deps-clean` / `deps-check` are created off
  (`OFF_ON_EXISTING_INSTALLS`).
- New config `cron_keep_background` (default false): `maxxing init` writes it once, true when the install already had
  default jobs (installed before a70) -> scheduled runs stay in the cron process as in a69 (no unit), so their
  background programs keep living (#49's intent); `KillMode=process` was tried and dropped: a leftover process keeps
  the fixed unit name `maxxing-cron-<id>` taken and the next run is skipped. New installs use the units (F07).
  `unit_hardening` is written the same way (false on those installs).
- Crontab lines carry `MAXXING_CRON_DETACH=1` instead of `--detach`: a69 (restored by a rollback or a test branch)
  refuses the unknown flag, so every job went silent; the variable is popped by `cmd_cron` and not forwarded by
  `spawn_run` (else the unit detached again, in a loop).
- `spawn.base_env`: our Node.js (`<state>/tools/nodejs/current/bin`) goes on a turn's PATH only when the server has
  no `node` (it came first even before the server's own); the legacy `<state>/tools/node` rule is unchanged.
- `cmd_cron`: `--detach` whose `systemd-run` fails (other than already running) runs the job in the cron process
  instead of exiting 1 into /dev/null with no run recorded.
- `license.fetch_latest`: the downgrade check compares with the installed version only, not with a version fetched
  into origin but never installed (rolled back, then withdrawn).
- install.sh: `PRIOR` (re-run); `SWAP=auto` adds swap only on a fresh server (`SWAP=1` forces it);
  a failed protection stops only a fresh install (`EXISTING`/`PRIOR` warn) - it stopped re-runs after the code was
  updated but before the service step.
- Tests that depended on the dev box: `chown` skipped without CAP_CHOWN, skills rendering ignores a code dir under
  /root/maxxing, default jobs test does not need the checkout's `.git`.
Kept as FEU wrote them: previews limited to static assets (F03), unit hardening on for new installs, jobs slice 75 %,
web MemoryMax drop-in, setup link valid 1 h, license `kid` / token rotation (the license server ignores
`machine_id` and sends no `token` yet: compatible).

## 2.0.0-alpha.69 - 2026-10-18

FEU's PR #48 (based on a67, numbered a72 there) and Romain's PRs #57 and #58 (#58 numbered a69 there), integrated
without their version files and rebuilt `web/dist`. Their notes follow, then what was changed at integration.

### #48
- `cmd_core.cmd_update`: `old` (rollback point, `refs/maxxing/pre-update`) is read BEFORE `--branch` checks out the
  new branch (it was re-read after, so a failed health check "rolled back" to the new code). `_UPDATE_CTX` keeps the
  start branch and whether web/ edits were stashed; `_back_to(old)` (used by `_rollback` and the conflict path)
  checks out the start branch (`-f`), `reset --hard old`, then `git stash pop` (warning if the pop fails: the edits
  stay in the stash). Auto-saved dirty edits after a branch switch no longer move `old`: the save commit sits on the
  new branch.
- `_update_rollback` (`maxxing update --rollback`): refuses (exit 1, nothing changed) while `customs.dirty_files()`
  is not empty, instead of `reset --hard` over them.
- Tests: `tests/test_update_safety.py`.

### #57
- `pages/sessions/Items.tsx`: `UserMessage` no longer shows the profile `PersonChip` (nor calls `useProfile`); the
  profile texts (`settings.profile.desc`, `profile.desc`) say the pseudo is used for web messages mirrored to Telegram.

### #58
UI kit for extensions + no emoji in the built-in cards, the "Your pages" extension and the packs.
- `server/maxxing/assets/ui-kit.css`: the design system as `ui-*` classes (layout, type, card, tile, icon box, buttons,
  fields, badge/dot, list, table, stat, progress, steps, callout, empty, skeleton, code/kbd/link), all from the theme
  variables, selectors in `:where()` (zero specificity: the extension's CSS wins), scoped to `.mx-ext` (page host) and
  the widget frame. Served at `GET /ext/ui-kit.css` (auth, `no-cache`); the extension page (`pages/ext`) adds it once
  as `<link id="mx-ui-kit">`. The widget frame inlines it after `WIDGET_BRIDGE`.
- HTML widget theme: `HtmlWidget` now sends the app's variables under their own names too (`--background`, `--card`,
  `--primary`, `--success`, `--radius`, `--row-h`, `--pad-card`...; the `--mx-*` aliases stay) and re-sends them when
  the accent, tint or density changes (was: theme only).
- Page `ctx.icon(name, {size?, className?})` -> a cloned `<svg>` of `NamedIcon` (rendered once per name with
  `createRoot` + `flushSync`, cached). `NamedIcon` set +27 names.
- Card list items: optional `icon` (kebab name; grid tile = accent-tinted box, plain list = muted 16 px icon); `emoji`
  still accepted. Built-in `activity` (first steps) and `customize` items use `icon`.
- Packs: `pack.json` + `Pack` get `icon` (basics = `home`); the project still gets the pack's `emoji`. `PackCard`
  redesigned; install toast without the emoji. Test: every pack icon exists in `icon.tsx`.
- `templates/workspace/extensions/pages` 1.1.0: rewritten on the kit (no gradient, no emoji); the a69 upgrade note
  replaces an untouched 1.0.0 copy. `examples/extensions/notes-page`, the skill `maxxing-extension` and docs 12/13
  use the kit.

### Adapted at integration (wins over the notes above)
- Detached start (a branch under test checked out with `git checkout --detach`, as our own test workflow does):
  `_current_branch()` returns `"HEAD"`, so `_back_to` "checked out" `HEAD` (no-op) and `reset --hard old` moved the
  branch the update had switched to (`--branch main`) onto the test commit - main then carried the test commits,
  later read as customizations. The start is now `""` for a detached HEAD and `_goto_start` runs
  `checkout -f --detach old` instead. Test `test_detached_start_rollback_does_not_move_main`.
- `--rollback` after a successful `--branch X` ran `reset --hard <main's old commit>` on X (X rewritten, still on
  X). The branch that ran is now recorded next to the rollback point, `<state>/update/pre-update-branch.json`
  `{commit, branch}` (used only while `commit` equals `refs/maxxing/pre-update`), and `--rollback` checks it out
  before the reset. Test `test_rollback_after_a_branch_switch_goes_back_to_the_branch_that_ran`.
- Conflict after `--branch X`: the PR now goes back to the start branch, but the printed instructions still said
  `git rebase origin/X` (it would have rebased main onto X) and `--resume` had lost the start branch (a failed
  resume reset X to main's commit). The instructions start with `git checkout X &&` after a switch, and `--resume`
  reloads the start branch from `pre-update-branch.json`. Test `test_conflict_after_a_branch_switch_resumes_on_that_branch`.
- After a branch switch, the uncommitted changes auto-saved by the update sit on the new branch, so a rollback left
  them off the running code. `_UPDATE_CTX["saved"] = (branch, sha)`; `_back_to` cherry-picks that commit onto the
  start branch after the reset (same customization), moves `refs/maxxing/pre-update` and the pending `from` to it
  (`_back_to` now returns the commit it ends on); a failed cherry-pick is aborted with a warning naming the branch.
  Test `test_branch_switch_rollback_keeps_the_auto_saved_changes_running`.
- Conflict with web/ edits set aside: the PR pops them back, so the printed `git rebase origin/<branch>` was refused
  by git (unstaged changes) and the adapt -> `--resume` path was broken. The instructions now start with
  `git stash push -u -q -m "maxxing update: edits of the web UI" -- web/` in that case (they stay aside, as after
  a successful update). Test `test_conflict_with_web_edits_prints_instructions_that_work`.
- `--rollback` refused on uncommitted changes advised `maxxing custom save` first, but the following
  `reset --hard refs/maxxing/pre-update` drops that new commit. The advice is now `git stash push -u`, rollback,
  `git stash pop`; the PR's test follows it and checks the change survives.
- #58: `WIDGET_BRIDGE` added an `mx-kit` class to `<html>` before the widget's markup is parsed; a widget starting with
  its own `<html class="...">` then lost that class (the parser ignores attributes of a second `<html>` tag that are
  already set). The kit is now scoped to a `data-mx-kit` attribute (`[data-mx-kit]` in `ui-kit.css`), set by
  `setAttribute`, which leaves the widget's own classes alone. Test in `test_extensions.py`.

## 2.0.0-alpha.68 - 2026-10-18

FEU's PRs #43-#47 and #49-#56 (each based on a67, numbered a68-a81 there), integrated in one release without their rebuilt `web/dist` and version files; #44 and #45 touched the same lines of `service._enqueue` and were combined. Their notes follow, then what was changed at integration.

### #44
Sessions core audit (A1, A5):
- `Runner._pop` clears `stop_flag` / `interrupted` inside its locked `store.edit` (was in `run()` after `_pop`
  returned): a SIGTERM / SIGUSR1 sent for the turn that was just popped (the server reads `pid` / `turn_id` once the
  lock is released) was wiped and the turn ran to its end.
- `service.stop` signals `pid` only while `store.runner_alive(sid, {})` (a runner holds the run lock), the same for
  the final SIGKILL; `_enqueue` sets `pid=None` when it spawns a runner, so the grace period of `runner_alive(sid, m)`
  (steer) never pairs a fresh spawn with a dead runner's pid. Before: a runner killed without cleanup left its pid,
  and Stop / delete sent SIGTERM to whatever process reused it (the server runs as root).

### #45
Sessions core audit (A2):
- New meta `handoff_pending` (float, set by `service.handoff` on the continuation): `_enqueue` queues without
  starting a runner while it is younger than `HANDOFF_HOLD_S` (600 s). `Runner._handoff` -> `_start_target` drops
  it, puts the seed at the HEAD of the queue (was appended after the messages sent meanwhile, which then ran in an
  empty thread) and starts the runner unless one is alive; a failed / stopped summary drops it and starts what is
  queued. The watcher (`_scan`, `_held`) calls `release_handoff(sid)` once the hold of a continuation with queued
  messages expires (the old runner died). `POST /messages` to a held continuation returns `queued:true`.

### #47
Follow-up of idle compaction (a67), from the sessions core audit:
- New meta `base_tokens` = `context_tokens` of the first call of the current thread (`Attempt.fresh`, set by
  `Runner.turn`, stored in `_finish`): the fixed part (system prompt, CLAUDE.md, memory). `_idle_compact` returns
  None when `context_tokens - base_tokens < max(idle_compact_tokens, IDLE_COMPACT_MIN) // 2`.
- The message put back behind the idle summary is marked `held: true` (dropped when it pops); `service.stop` keeps
  `held` items, so a Stop during the summary cancels only the summary and the message runs in the full thread
  (before: `stop` emptied the queue and the message was lost).
- `aside.ask`: `store.update(sid, cache_at=...)` ignores a session deleted while Claude answered (was a
  `KeyError` -> 500).

### #46
Sessions core audit (A4):
- New state file `<state>/session-watcher.json` `{at}`: when the session watcher last passed (written every
  `PASS_STAMP_S` = 5 s and right after a pass that reported turn ends). The first pass after a start (`_scan(False)`)
  still takes its baseline but also reports sessions not running whose `finished_at` > that stamp (`_last_pass()`):
  before, a turn that ended while the server was stopped or restarting never reached `on_turn_end` (no Telegram
  reply, no notification). No file (first start): nothing reported. A turn that ends during the very pass that
  reports it may be reported once more after a restart (never lost).

### #52
- `sessions/runner._claude_in_use(note=None)`: when the shared flock on `<state>/.claude-update.lock` is not free at
  once (an update holds it exclusively), one `mx_note` "Claude Code is being updated..." is written to the session;
  after UPDATE_WAIT_S (420 s, above `claude_update.UPDATE_TIMEOUT_S`) a `warn` note and the turn starts anyway.
  `Runner.attempt` passes `self.note`. Still stdlib-only.
- `claude_update.runs_here()`: the loop only starts when MAXXING_STATE is `/var/lib/claude-maxxing`
  (`DEFAULT_STATE`); `MAXXING_CLAUDE_UPDATE=1` forces it on another state dir, `=0` turns it off everywhere. A dev
  server (ports 8801-8809) or a test copy of the state updated the CLI of the whole machine.
- Tests: `tests/test_claude_update_safety.py` (turn started under the exclusive lock: no Claude call until release,
  note in the log; wait limit; `runs_here`).

### #43
- `GitGraph`: lane width follows the list width (`ResizeObserver`; at most 34 % of it, 7 to 16 px per lane);
  `layout()` returns `span` per row (rightmost lane drawn on it) and the row text is indented by its own span, not by
  the widest row (14 open branches left 0 px for the subject on a phone and on desktop with refs). Ref badges are
  `min-w-0` with a truncated name and `title`; the refs group shrinks (max 60 %), the subject keeps `min-w-12`.
- `GitPage` repo view: below `lg` (1024 px) the commit detail is a bottom `Sheet` (`useMediaQuery`); the side column
  keeps only the pull requests there. List toolbar: the filter is `flex-1` next to the refresh button on a phone.
- Audit script used: widths 1583 / 1280 / 1024 / 768 / 390, no horizontal overflow, no subject narrower than 48 px.

### #53
- `api/files.py`: `_guard_workspace(p)` in `_move` (source) and `_delete`: `workspace.root()` or one of its parents
  `403 forbidden`; a path under the workspace goes through `workspace._ensure_idle(rel)` -> `409
  has_running_sessions` (same as the workspace API).
- `resolve()`: `ValueError` (NUL byte) / `RuntimeError` (symlink loop) -> `400 bad_path` instead of 500.
- `_mkdir`: a dangling symlink at the path is `409 exists`; `FileExistsError` / `NotADirectoryError` from
  `mkdir(parents=True)` (a file in the way) -> `409 exists`.

### #54
- `api/tasks.py`: `save()` compares the file's `(mtime_ns, size)` with the signature `load()` cached in the same
  `_lock` transaction and raises `_Changed` (cache dropped) when it differs. Every write route is wrapped in
  `_retry_on_change`: the handler runs again on the fresh file (nothing was written by the failed attempt), up to
  3 times, then `409 conflict`. The UI already rolls back its optimistic change and toasts on a 409; the watcher
  then refetches.
- `_norm_task`: `id` / `title` / `notes` / `project_id` / `topic_path` of another type are turned into text
  (`_text`: lists and objects as JSON), non-numeric `created` / `updated` / `done_at` replaced. A list in `notes`
  made `search._index_tasks` fail on the SQLite insert, so the whole refresh rolled back on every run.

### #55
- `importer._entries`: `FOLDER_SETTINGS` (`.maxxing.json`, `.order.json`) anywhere in the path -> skipped
  ("Harness folder settings (not imported)"), in the preview and on apply. `.maxxing.json` carries the topic
  `permission_mode`.
- `importer.apply`: `_check_dest(dest, root)` - `dest.resolve()` must stay under `root.resolve()` or the (possibly
  linked) `.claude/skills` - then `mkdir(parents=True)` and an `is_dir()` check; any `OSError` / `ValueError` there
  adds the entry to `skipped` and the loop goes on (was a 500 after projects / topics were already created, with
  no report).

### #56
- `trash._free_dir_name`: the base name is cut to `48 - len(tag)` (trailing dashes stripped) before
  `-restored` / `-restored-N`, so the result still matches `workspace.SLUG_RE`; was `<48 chars>-restored`
  (57), skipped by the workspace tree.

### #49
- `crons._run_shell`: stdout/stderr go to a pipe drained by a daemon thread (`read1(64 KiB)`, keeps the last
  `OUTPUT_TAIL` bytes + total size) instead of a `tempfile.TemporaryFile` (whole output on /tmp, often a tmpfs = RAM).
  `reader.join(timeout=2)` after the exit, so a background child that keeps the pipe open does not hold the run.
  Return value unchanged (`…` prefix when cut, timeout note).
- `crons.split_crontab`: BEGIN without END -> only lines containing ` cron run ` count as managed; the others go back
  to `outside` (they were dropped by `sync_crontab`).
- Tests: `tests/test_cron_safety.py`.

### #50
- `feedhooks.deliver`: for `BODY_DEDUPE` kinds (shopify, github) the dedupe key is `_replay_key(kind, headers, body)`
  = `sha256:<topic>:<hex sha256 of the raw body>` instead of the `X-Shopify-Webhook-Id` / `X-GitHub-Delivery`
  header (not covered by the HMAC: a replay with a new id posted again). Shopify keeps a known topic in the key
  (`_SHOPIFY_TOPICS`; others -> `other`) because an order paid at once is sent with one body for orders/create and
  orders/paid. Existing rows keep their old keys (a replay of a pre-a74 delivery can post once more).
- `feed.post`: `sqlite3.IntegrityError` on the `events_dedupe` unique index (SELECT-then-INSERT race between two
  requests) -> `None` (duplicate) instead of a 500; still raised when there is no dedupe key.
- Tests: `tests/test_webhooks_replay.py`.

### #51
- `telegram.gateway._sync_sessions`: a failed `deleteForumTopic` drops the `session_threads` mapping only when
  `_thread_gone(e)`; 429 (a `retry_after` longer than the client waits) now stops the pass like a network error
  (`res.error` "Telegram asks to slow down: ..."); any other error keeps the mapping and moves on (was dropped:
  the thread became an orphan nothing would ever delete).
- `telegram.gateway.feed_message`: the body is cut to 700 characters before `fmt.escape` (cutting after could split
  `&amp;` / `&lt;` and Telegram refused the HTML).
- Tests: `tests/test_telegram_sync.py`.

### Adapted at integration (wins over the notes above)
- #48 (update rollbacks) is NOT in this release: with a detached HEAD (testing a branch on a server) `--branch main`
  then a failed start moved `main` onto the tested commit; `--rollback` after a successful `--branch X` reset `X` onto
  the old branch's commit; on a conflict the restored `web/` edits blocked the suggested `git rebase`, and with
  `--branch` Claude was left on the starting branch. Sent back to its author.
- #47: `base_tokens` = `Attempt.first_context` (usage of the first assistant message of a fresh thread), not the
  thread's context at the end of its first turn (which included every tool output of that turn and could skip a
  useful summary). A thread restarted after `_resume_lost` is fresh too.
- #49: when the output reader is still alive 2 s after bash exits (a background child holds the pipe), a detached
  `cat` (`start_new_session`) keeps draining it: once `maxxing cron run` exits, the child's next write would
  otherwise die of SIGPIPE (it used to write to the unlinked temp file and live). Test
  `test_background_child_keeps_writing_after_the_run` (runs the job in a process that exits).
- #51: a failed `deleteForumTopic` keeps the mapping only for transient errors (network / 429 stop the pass, 5xx
  skip the session); other 4xx (no right to manage topics, bot removed) drop it as before, so a refusal is not
  retried at every sync.
- #52: `claude_update.runs_here()` is also true inside the installed service (`/proc/self/cgroup` ends with
  `/claude-maxxing.service`), so an install with another `STATE_DIR` keeps automatic Claude Code updates.
- #54: `_num` also reads numeric text and ISO dates (`"1767225600"`, `"2026-10-01"`) instead of replacing a
  hand-written date with now / None.

## 2.0.0-alpha.67 - 2026-10-18

FEU's PRs #27-#42 (based on a65, then on a66), integrated in one release without their rebuilt `web/dist` and version files. Their notes
follow, then what was changed at integration (it wins over the notes).

- `gitview._git`: `SAFE_GIT` (`core.fsmonitor=false`, `core.hooksPath=/dev/null`, `log.showSignature=false`,
  `gpg[.ssh|.x509].program=false`, `diff.external=`) + `_filter_overrides(repo)` (`filter.<name>.clean/smudge=cat`,
  `process=`, `required=false` for every driver of `git config --includes --list` - all scopes, so
  `config.worktree` too; cached on the mtimes of config / config.worktree / .git, never when includes are used) and
  `GIT_ATTR_SOURCE=<empty tree>` (the worktree's `.gitattributes` assigns no filter or diff driver);
  `--no-show-signature` on log/show, `--no-ext-diff --no-textconv` on `show --numstat`; env `GIT_CONFIG_NOSYSTEM=1`,
  `GIT_EXTERNAL_DIFF=`. `safe.directory=*` removed (git's ownership check, CVE-2022-24765). Repro before the fix:
  `core.fsmonitor` ran on `git status`, `gpg.program` on `git log -1` of a commit with a forged `gpgsig`. Tests
  `test_repo_config_never_runs_programs` (fails on 2.0.0a58), `test_worktree_config_filters_never_run`.
- GitHub: one shared `httpx.Client` (`_client()`); `_cached` builds once per key (lock, others wait); 403/429 with
  `x-ratelimit-remaining: 0` or `retry-after` -> 429 `rate_limited`; non-JSON body -> 502; `_one_token` skips
  malformed repos and reports an odd `/user`; `_repo_tokens` re-lists accounts only when no known token sees the
  repo and drops tokens no longer in the vault; `clear_cache` also clears `_access`; `_ts` uses `calendar.timegm`;
  remote URL masking `//[^/]*@`; local graph keeps the first `MAX_BRANCHES = 20` branches.
- `_cached`: an expired value is returned at once and rebuilt in a background thread (one at a time; `refresh=1`
  still rebuilds now). Measured: the repository list (48 repos x 3 git calls) cost 311-378 ms every 60 s on the
  request that found the cache expired. Test `test_expired_cache_answers_at_once_and_rebuilds_behind`.
- `gitview.local_repos`: a linked worktree (`.git` file -> `<clone>/.git/worktrees/<name>`, `_main_clone`) whose
  clone is also under the files root is counted on that clone (`worktrees` field) instead of listed; submodules
  and separate git dirs stay repositories; a worktree path still opens (`resolve` / graph unchanged). Web: the
  local repository card drops the branch chip and shows `git.worktrees`. Test
  `test_worktrees_are_not_listed_as_repositories`.
- `api/sessions._sse`: `_probe` (two `stat()`) runs inline instead of `asyncio.to_thread` every `POLL_RUNNING_S`
  tick (no thread hop, no wait on a busy default pool; latency unchanged).
- `service.models()`: `_models_seen[sid] = (inode, bytes scanned, ids)`; a pass reads only the appended bytes
  (still capped at the last 300 KB), a rewritten log (new inode or shorter) is scanned again. Bench (17
  conversations): 7.8 ms -> 0.6 ms per pass. Test `test_models_scan_only_new_bytes`.
- Looked at and left as is: the first load preloads only static imports of the entry (no unused chunk); `web/dist`
  holds no stale chunk (every file is tracked).
- `health.cpu_pct`: no 0.25 s sleep (baseline taken at import, any interval accepted, calls < 1 s apart repeat the
  last value). Measured: `/api/system/health` 277 ms on the first call after a pause, ~25 ms now.
- `Textarea`: `onChange` resizes only when uncontrolled (controlled: the layout effect on `value` does it).
  Measured (4x CPU throttle, 56 keys): 281 -> 169 layouts, 840 -> 590 ms of layout + style.
Web robustness (crash / freeze review of a55-a58), web only:
- `components/ui/error-boundary.tsx`: `ErrorBoundary` (variants inline / card / page, `resetKey` retries on new
  data, chunk errors offer Reload). Around: the app root (outside the router: dialogs, toasts), each dashboard
  `WidgetCard` and each of its blocks (`clean_card` only checks block types), each thread `ItemRow`, the
  `FileViewerHost`, the HUD's PiP root. Text `error.part`.
- `main.tsx`: `vite:preloadError` -> one reload per minute (sessionStorage stamp; none without storage).
- `lib/utils` `store.get/set/remove`: localStorage that never throws; used by `viewerStore` (read at module load:
  blocked storage was a blank app), onboarding, AppShell.
- `DiffView` renders the first `DIFF_ROWS` (400) rows + "Show N more lines". `Markdown` over `MAX_MARKDOWN`
  (300k chars) renders a plain `<pre>`. `log.ts`: a log without listeners for `EVICT_MS` (2 min) leaves the cache.
- `diagram.tsx`: a failed `import('mermaid')` is not cached. `MediaPlayer`: `webkitEnterFullscreen` fallback (iOS).
- Checked with Puppeteer on the bench against main a58 (all three fail there): malformed dashboard cards, blocked
  storage, a missing lazy chunk.
- Turn and cron units: `spawn.memory_properties()` adds `--property OOMPolicy=continue` and
  `--property MemoryMax=<unit_memory_max>` (new config key, default `"75%"`, `""` / `"infinity"` = no cap,
  anything not matching `^\d+(\.\d+)?[%KMGT]?$` ignored) to `_start_unit` and `crons.spawn_run`. Why: with the
  default `OOMPolicy=stop`, a kernel OOM kill of one process (seen: ffmpeg with 54 PNG-sequence inputs at
  4.9 GB, global OOM, no swap) made systemd stop the whole runner unit -> the turn ended with no answer. Now only
  that process dies (exit 137, Claude reads "Killed") and the kill happens inside the unit's own cgroup before
  the server runs short. Checked on a real unit: `continue` keeps the parent running, `stop` fails the unit;
  `MemoryMax=75%` = 5.7 GB on a 7.7 GB server. Tests: test_spawn_tuning, test_crons::test_spawn_systemd.
- `spawn.unit_end_reason(unit)`: `journalctl -u <unit> -n 30 -o cat`, last run only (after the last
  `Started` line: the unit name is reused by every turn) -> `"oom"` on `result 'oom-kill'`. `service._effective`
  uses it when it repairs a session found dead while running: error "The turn was stopped: the server ran out
  of memory." instead of "ended unexpectedly (server reboot or crash)". Test: test_sessions::test_dead_runner_*.
- `skills/video-motion-design`: section 4, ffmpeg memory (one `movie=` ffconcat source instead of dozens of
  future `-i` inputs, `option framerate 30` on every list entry; keep audio and video on the same clock; test a
  range under a cap and the list timestamps first).
- Doctor `caddy_site`: the fix is `cp -p <site> <site>.bak && <seds> && caddy validate --config <Caddyfile>
  --adapter caddyfile && systemctl reload caddy` (was: seds then reload, no copy, no validation). The body-limit
  check compares with `CADDY_BODY_MB` when `upload_max_mb` is 0 (no app cap: Caddy's 500 MB was not flagged),
  and its sed also rewrites a bare byte count (`max_size 524288000`). Found while applying the a48 note on a
  real server. Test: test_hardening::test_doctor_flags_an_old_caddy_site.
- `MediaPlayer`: the custom speed and quality menus (`PlayerMenu`, `QualityMenu`, `MenuRow`) are replaced by
  `PickButton`, an invisible native `<select>` over the button (OS picker on touch, never clipped by the player box,
  works inside the fullscreen element, Escape handled by the select). The key handler ignores events from a
  `SELECT`. i18n keys `media.qualityReady`, `media.qualityMake`, `media.qualityHint` removed.
- `useVideoQuality(path, enabled, version, active)`: Auto asks `POST /api/files/video/prepare` only when `active`
  (the video was started); an explicit choice still prepares at once.
- `Viewer` `useSwipe`: a touch starting on a button, select, input or slider does not swipe to another file.
- Web only. `Items.tsx`: `useMessageMenu` (right click / Android long press menu at the pointer: Copy, New session
  from this message, Edit, Delete) on user messages (any) and assistant replies; skipped on a link, when a selection
  is inside the message (browser menu + QuotePill) and on files (`FileMenu` captures first). Edit / New session run
  from `onCloseAutoFocus` (a closing Radix menu takes the focus back otherwise - lost focus on phones).
- `store.ts` seeds: `seedComposer(draftKey, {text, quotes, attachments})` / `takeSeed` / `onSeed` (event `mx-seed`):
  a composer applies its seed on mount or at once if open. `ComposerHandle.bringBack(seed)` (also used by the queue's
  Edit): text first then the typed draft, quotes, attachments as already-uploaded paths (thumbnail via `thumbUrl`,
  no size shown).
- `Thread` props `onEdit` / `onFork`; Edit = `bringBack` + hide without the Undo toast. `SessionColumn.onFork` seeds
  `new:<path>` and navigates to `/sessions?path=<path>&new=1` (opens the "new session" column, on a phone too).
  Offered only when the session has a topic. Showcase `msg-actions`.
- Composer: `editQueue` is optimistic when every queued message is known to the tab (`queued.length ===
  queueCount`): `bringBack` at once, the stack hidden (`taken`), then the `/queue/take` answer reconciles (text
  swapped only if the composer still starts with what was put there, attachments added / removed); on error the
  inserted text and attachments are taken out and the stack shows again. Clear: `onClearQueue` may return a
  promise, the stack hides at once and comes back on rejection. Attachments: `[data-testid=composer-attachments]`
  `max-h-[6.75rem] overflow-y-auto`, scrolled to the end when files are added. Audit
  `responsive-audit/composer-instant.mjs` (take answer delayed 1.5 s: text in 62-78 ms, desktop + mobile).
Robustness (crash / wedge review of a55-a58):
- `extensions._import` runs `exec_module` in a daemon thread joined with `IMPORT_TIMEOUT_S` (10 s); `SystemExit` /
  `BaseException` from api.py stored as the extension error (it used to stop startup / loop the service).
- `extensions.call(fn, *a, timeout)`: extension code (`handle()`, extension `card()`) on `_pool` (`EXT_WORKERS` 4)
  with a busy counter released when the code returns; none free -> `ExtensionBusy` (API 503 `extension_busy`,
  dashboard card error). A stuck `handle()` used to keep a thread of the default executor (8 on 4 CPUs) per call
  until every `to_thread` caller (streams, routes, watchers) waited.
- Background loops never die on one error: `api/search._loop`, `telegram.Gateway._watch_sessions` (try inside the
  loop). Telegram offset kept in memory (`Gateway._offset`, wins over the file), failed `offset.json` write logged
  (it used to restart `_poll` on the stale offset = updates replayed every 5 s). `client._parse` tolerates a
  non-dict body / junk `error_code`.
- `service._scan`: `public()` per session in a try (one bad session file stopped every turn end); `public()` uses
  `_num()` for turns / cost / finished_at / seen_at. A session going to `error` without a new turn is reported from
  any previous state (spawn failure within one pass was never reported). `_fire` tasks referenced (`_firing`).
- `runner._lines_until_exit`: stdout read by a pump thread; once Claude exited, `STDOUT_GRACE_S` (10 s, env
  `MAXXING_STDOUT_GRACE_S`) then the turn ends even if a background program (own session) keeps the pipe open.
- `config.ProcessLock`: `config._lock` and `crons._lock` are re-entrant thread locks + `flock` on
  `<state>/.config.lock` / `.crons.lock` held by the outermost holder (server, CLI, cron runs, runners). `_atomic_write`
  fsyncs before the rename. `store._write` removes its tmp file on failure.
- `config._merge`: a non-dict value over a dict default is ignored; `workspace()` / `files_root()` fall back to the
  default when empty. `crons.list_jobs` tolerates run lines without `at`/`ok` and broken schedules;
  `api/tasks` raises `CorruptFile` when `projects` / `tasks` is not a list.
- Tests: bad import (exit / hang), stuck handle (504 then 503, rest of the API answers), damaged session file,
  background program holding stdout (fake_claude `ORPHAN`), damaged state files, cross-process config lock, odd
  Telegram answers.
- Review fixes: `runner._lines_until_exit` checks `p.poll()` on every pass (a background program that keeps
  writing no longer holds the turn open; fake_claude `CHATTY`, test `..._keeps_writing`); `extensions.call` frees
  its slot in the future's done callback (also when cancelled before it started); `_scan` remembers a damaged meta
  file by mtime (`_damaged`, logged once); `config.write_json` takes the machine-wide lock only for config.json /
  secrets.json (other files: unique temp file + rename); the Telegram offset is written off the event loop.
- `POST /api/files/stat` (batch mtimes, ≤ 500 paths, confined like every files route). Web: `useFileStamp(path)`
  (react-query `['files','stamp',path]`, requests batched per tick in chunks of 200, staleTime 30 s, under the
  `files` key so every file mutation refreshes it), `knownFileStamp`, `refreshFileStamps`; `<Thumb>`
  (`features/files/Thumb.tsx`) renders once the stamp is known (never an unversioned load then a versioned one).
  Used by chat thumbnails, quoted files, the HUD, the viewer (`PreviewBody` version for image / video / audio /
  font, its blurred placeholder, neighbour prefetch). `useSessionStream`: a `tool_result` or `result` event refreshes
  the stamps (throttled 800 ms), a `result` invalidates `['files','list']`. `/api/files/thumb` without `v`:
  `private, no-cache` (revalidated) instead of `max-age=86400`. Tests: stat route, thumb cache headers.
- `infra.ssh_command`: `--` before the destination. `registry.load()` keeps only servers `check_server` accepts
  (`key_must_exist=False`; host may not start with `-`; key path may not start with `-`). `spawn.deny_rules`:
  `Edit(/<workspace>/infra.json)`. Repro before: `user: "-oProxyCommand=touch X"` ran on every refresh.
- `caddy._block`: path sites behind `reverse_proxy` get `header_up -Cookie`, `header_up -Authorization`,
  `header_down -Set-Cookie`; `file_server { hide .* }`. `add_site(root=)` refuses the workspace root, `$HOME`,
  `/home`, anything under STATE, CODE, `~/.ssh`, `/etc` or a dot folder, and paths / `project` outside
  `[A-Za-z0-9_./-]` (written unquoted in the Caddy file). Checked with Caddy 2: `.env` -> 404, cookie and
  Authorization not forwarded, Set-Cookie dropped.
- `check_url` catches `httpx.InvalidURL` / `ValueError` (`unknown`, `invalid_url`); `parse_nginx` strips a leading
  `.` and skips `~regex` names. `refresh()` reads every probe / provider future through `_result` (an exception
  = that section's error). `providers._ODD` (HTTPError, ValueError, KeyError, TypeError, AttributeError) caught in
  `_section`, the Cloudflare account lookup, DNS / worker routes / R2 domains, Hostinger zones.
- `api/infra.annotate`: snapshot patched in a thread under `infra.snapshot_lock` (shared with the refresh write).
  Garage config created with `os.open(..., 0o600)`.
- Tests: `test_infra_json_cannot_run_commands_through_ssh`, `test_path_sites_never_see_the_session`,
  `test_odd_hosts_and_providers_never_stop_a_refresh` (all three fail on 2.0.0a59).
- Connect (2.0.0a60): `connect._connecting(target)` - one connect per host / VPS at a time (also the refresh's
  `auto_connect`), at most `MAX_CONNECTS = 2` at once (each can wait `ADD_WAIT_S`), 409 `in_progress` / `busy`;
  `ensure_key` under a lock (two first connects never race ssh-keygen) and its failures as `ConnectError("no_key")`;
  Hostinger network / odd answers as `ConnectError("hostinger_error")` (were 500); the line to paste adds the key
  with `restrict` and `chmod 700 ~/.ssh`; `/servers/rename` patches the snapshot in a thread under
  `infra.snapshot_lock`. Test `test_connect_guards`.
- Faster refresh (measured 6.4-6.8 s, almost all network checks): URL and certificate checks are submitted together
  (the certificates waited for every URL), connect timeout 3 s per address for both (a dead IPv6 address cost 3-6 s
  before the IPv4 one was tried).
- `sessions/titles.py` (INTERNALS.md#maxxing.sessions.titles): `create_session` without a title and with a message
  keeps the 60-char provisional title, then a daemon thread (2 at a time) runs `claude -p --output-format json
  --model claude-haiku-4-5-20251001 --tools "" --no-session-persistence --strict-mcp-config --system-prompt …`
  (stdin = first 1000 chars, cwd `<state>/claude-titles`, 30 s timeout; measured ~2.5 s, ~400 input tokens) and
  writes the answer (`clean()`: one line, <= 60 chars, <= 8 words) under `store.edit` only if the title is still the
  provisional one, then `bus.invalidate("sessions")`. Failure / timeout / unusable answer -> `heuristic()` (first
  sentence, FR/EN filler stripped, 40 chars on a word boundary). Cron, memory and update sessions pass titles:
  untouched. The runner is unchanged (stdlib-only).
- Sessions created without a message (empty API session "Session N", Telegram sessions: the gateway creates then
  sends) get meta `title_auto`; `send_message` -> `titles.first_message` replaces the title on the first message
  only while it is still that one. `create_session(auto_title=True)`: Telegram `_start_new` when the title came
  from the first message (not the user's thread name / `/new` title); "Telegram", `/new <title>` and "About: …"
  keep theirs. The thread follows through `bus.invalidate("sessions")` -> `sync_threads` (debounced 3 s).
- Config `short_titles` (default true), in `GET /api/claude/status` and `PUT /api/claude/settings`; switch in
  Settings -> Claude (`claude.shortTitles*`). Env `MAXXING_SHORT_TITLES=0` turns the call off (set by conftest; tests
  opt in). Fake claude: `--tools` / `--system-prompt` take a value; a "name chat sessions" system prompt answers
  `$FAKE_CLAUDE_TITLE`.
- Idle compaction: config `idle_compact_tokens` (60000; 0 = off; raised to `IDLE_COMPACT_MIN` 20000) and
  `idle_compact_after_s` (3600), `GET /api/claude/status` + `PUT /api/claude/settings` (after_s 300..604800).
  `Runner._pop` checks `_idle_compact()` on the popped item (meta `finished_at` / new `cache_at`, `context_tokens`,
  `fresh`, `cron`, `plan_ready`; item kind `user`, source not system/cron, no steer / plan approval): it puts the
  item back at the queue head and runs a `compact` item (`auto: true, idle: true`) first, with an `mx_note`
  "Back after ...". `_post` of an idle compact sets `preface` (the SEED_COMPACT text) on the waiting message instead
  of queueing a `seed` item, so no extra turn; `build_prompt` prepends it (the displayed `mx_user` text is unchanged).
  A failed summary leaves the thread as it was and the message runs in it.
- `aside.ask` records `cache_at` after a side question (the fork read the thread, so its cache is warm).
- Web: `ClaudeDefaults` select `idle-compact` (data-tour), showcase `idle-compact`, i18n `claude.idleCompact*`,
  `show.idleCompact.*`.
- New `maxxing/claude_update.py`: background loop (started by `api/claude.py` `startup`, first pass after 10 min,
  then every 5 min) reads the npm registry latest (`depcheck.claude_latest`) at most every 6 h; when newer than
  `claude --version` and `busy_reason()` is None (no session `running`, no waiting queue outside `error`, no
  `aside` question, no cron lock held, newest `finished_at` > 10 min ago - checked again just before), runs
  `<claude_bin> update` (native installer or npm global, Claude Code picks) in `asyncio.to_thread`, timeout 5 min,
  then re-reads the version (an update leaving the version unchanged is a failure). A failed version is retried
  after 6 h; feed `system` item on success, on failure once per version (`dedupe=claude-update-failed:<v>`).
- State `<state>/claude-update.json` `{checked_at, latest, installed, last:{from,to,at,ok,error}, failed_version,
  failed_at}`. Config `claude_auto_update` (default true), `PUT /api/claude/settings {claude_auto_update}`,
  `GET /api/claude/status` adds `auto_update:{enabled, checked_at, latest, last}`.
- Doctor `claude_version` says whether the server will update it (or why the automatic update failed).
- Tests: `MAXXING_CLAUDE_UPDATE=0` in conftest; `tick()` with `installed_version` / `latest_version` / `run_update`
  monkeypatched (tests/test_claude_update.py). `MAXXING_CLAUDE_UPDATE_DELAY` = seconds before the first pass.
- Web: switch + last update line in `features/claude/ClaudeDefaults.tsx` (`data-tour="claude-auto-update"`), showcase
  `claude-auto-update`.
Security review of a55-a58 (findings proven on the code / bench first):
- `api/filesite`: folder tokens serve `ASSETS` extensions only (403 otherwise); `_single_file` also for the
  workspace root, `projects/`, `extensions/`, each project and its `topics/`; tokens carry `s` = the minting
  cookie's id (`security.session_id`) and stop with its revocation (`security.session_revoked`). `/site-url` takes
  the request. `read_token` compares bytes (no 500 on non-ASCII).
- Telegram *Ask Harness* (`_ask_about_event`): `new_session(..., plan_mode=True)`; the event text between random
  `NOTIFICATION-XXXXXXXX` markers (stripped from the content).
- Crons: `claude_access` (default false): `_job_env` adds `spawn.auth_env()` only then; vault `expose` keys always.
  `_load_raw` fills a missing `claude_access` with "the command calls claude" (`_CALLS_CLAUDE`), so a51 jobs keep
  working. Web: switch in the shell job editor. API/skill updated.
- Backup restore: `_hold_new_jobs` disables restored jobs (shell **and** Claude) not already here with the same id
  and the same `_JOB_CODE` fields (kind, command, prompt, topic, permission mode, model), except `maxxing backup
  run`; `_hold_new_extension_code` adds extensions any of whose `.py/.js/.mjs/.html` files was written to
  `extensions.disabled`; `_strip_hooks` removes `hooks` from any `.claude/settings(.local).json` it restores;
  restored skills and `customizations/*.patch` are listed in `held.review`; `_split_mcp` restores remote MCP servers
  only - local (stdio) ones missing here go to `<trash>/mcp-held.json` (0600) and `held.mcp`. Result `held` {crons,
  extensions, hooks, mcp, review}, feed notice `backup-restore-held`.
- Preview links: in folder mode, a page in the workspace never gets files under an `attachments/` folder (the
  uploads of a topic); a page saved among the uploads gets its file alone.
- `feedhooks`: `_same()` byte compare; signed sources rate-limited after the signature. `feed.post`: links
  `//host`, `/\host` dropped. `api/files._write`: mkstemp temp file (no write through a planted link).
  Thumbnails: widths bucketed (`THUMB_WIDTHS`), cache trimmed to 80 % of `THUMBS_MAX` (512 MB) at most every 10 min.
  `videos`: `MAX_QUEUED` 20, ffmpeg stderr to a temp file (a full stderr pipe stalled the single encode slot).
- Checked, not changed: ffmpeg 8 refuses an HLS playlist under a video name and absolute / unsafe concat entries
  (no local file read through a crafted video); the setup token, cookie flags and scrypt cost stay as they are.

FEU's PR #41 and #42 (opened after the review, added to the same release):
- Security round 4 (audit of a61-a64), two-step sign-in (`twofactor.py`):
  - server-wide budget of wrong codes `BAD_MAX` = 20 per `BAD_WINDOW` = 1 h (`_bad`): once spent, `check` returns
    `codes_paused` without comparing (no oracle) -> `POST /api/auth/two-factor` `429 codes_paused`; Allow still works.
    Before: every client had 5 requests x 5 codes per 15 min and a killed request freed its pending slot -> ~1000
    guesses/h from 40 addresses (one IPv6 /64).
  - `security.client_key`: an IPv6 client is its /64 (IPv4-mapped -> the IPv4) for every throttle (login too).
  - pending list: `PENDING_PER_CLIENT` = 3 (a new request of the same client drops its oldest), a full list
    (`PENDING_MAX`) drops the oldest instead of refusing everyone with 429 (lock-out by 2 clients before).
  - `check` prunes first: an approved but uncollected request dies after TTL + GRACE (it never expired before);
    `revoke_all()` (called by `security.set_password`, `forget_devices`, so `set_on(False)` too) drops every request.
  - code must match `[0-9]{6}` and is compared as bytes; `mx_device` must match its format before `compare_digest`
    (non-ASCII -> TypeError -> 500 before, a planted cookie broke the owner's sign-in).
- Infra (`platforms.py`, `registry.py`): Vercel `pages()` stops on an empty page or a repeated cursor (an endless
  loop held `infra._lock`: the page froze until a restart); the teams call also catches `httpx.HTTPError`, and
  `read_all` keeps only the type name of non-`ProviderError` exceptions (an httpx header error quoted the token);
  `clean_domain` turns IDNA `UnicodeError` into `invalid_domain` (500 -> 400).
MCP safety fixes (`maxxing/mcp.py`), no API shape change:
- `_Login` (OAuth pty): `closed` event checked by the reader loop; `close()` is idempotent (check-and-set under
  the lock), kills the CLI's process group, waits for it, joins the reader and only then `os.close`s the fd (it
  leaks it if the reader is still alive): the reader could otherwise `read()` a reused fd number and steal another
  component's data. `write()` runs under the lock and raises `404 login_expired` once closed.
- `login_start` resolves the folder before `openpty()` and closes the master on any exception (`folder_missing`
  and Popen errors leaked it); a Popen `OSError` is `500 cli_failed`. `_cli` maps `OSError` the same way.
- `login_finish` marks the login `finishing`: a second Finish meanwhile is `409 busy`; a Cancel during it is
  `404 login_expired`; no double close nor write on a closed fd.
- Abandoned logins: `_gc()` runs from `overview()` (GET /api/mcp), `login_start`, `login_finish` and a daemon
  reaper thread (`GC_EVERY` = 30 s, stops when no login is left); a new `login_start` for the same server id
  replaces (closes) the previous one. `_logins` is guarded by `_logins_lock`.
- Masking (`servers()` and the backup `export()`): every header / env value is masked (`•••`, `""` in the export)
  unless, once `${KEY}` references are removed, only an auth scheme word (`Bearer`, `Basic`, `Token`...) and
  separators are left (`REFS_ONLY_RE`); headers in `PLAIN_HEADERS` (Content-Type, Accept...) stay visible. URLs:
  userinfo -> `•••@` (dropped in the export), query / fragment values masked unless references, a token in the
  host or path still masks the whole address. `literal_secret` is true when anything was masked. There is no edit
  endpoint (add / remove only), so a mask is never written back.
- `_dict()` / `_list()` around every `mcpServers`, `projects`, `headers`, `env`, `args`, `enabledMcpjsonServers`
  read: a string or a list there (hand-edited `.mcp.json` / `.claude.json`) no longer raises (500 on GET /api/mcp,
  dead check thread).
- `NAME_RE` = `\A[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}\Z` (no leading `-`, no trailing newline) and `--` before the
  name in `add-json`, `remove` and `login` (checked against the real CLI 2.1.296).
- `_write_cfg`: temp copy of `.claude.json` created with `os.open(..., O_EXCL, 0o600)` under a unique name per
  call, then `os.replace` (it was 0644 until a later chmod, under one shared name).
- Tests: `tests/test_mcp_safety.py`; the fake CLI ignores `--`.

Adapted at integration:
- #30 `extensions.call`: calls queue on `_pool` (no busy counter); `ExtensionBusy` only when `_stuck` (calls past
  their timeout still holding a thread) >= `EXT_WORKERS` - the dashboard's `gather` of 5+ widgets used to get 503.
  `config.ProcessLock` waits at most `FLOCK_WAIT_S` (10 s, `LOCK_NB` polling) then goes on with the thread lock.
- #33 `health.cpu_pct`: after > 600 s without a call, a fresh 0.1 s sample (not the average of the pause);
  `service._models_seen` forgets deleted sessions.
- #27 doctor `caddy_site` fix: `{ caddy validate … || { cp -p site.bak site; false; }; }` before the reload.
- #28 `MediaPlayer`: `toggle()` and the original's `onError` set `started` (Auto copy for HEVC / ProRes originals).
- #29 `useMessageMenu`: long press (550 ms, < 8 px move, no selection) opens the menu (iOS Safari never fires
  `contextmenu`).
- #35 `fileListQuery` seeds `known` stamps (`seedFileStamps`); `useFileStamp` uses a known stamp as `initialData`
  (viewer opens at once); `fileStamp(p)` for neighbour prefetch (versioned URL, no double download).
- #36 path sites: `header_up Cookie "mx_[A-Za-z0-9_]+=[^;]*;?\s*" ""` + `header_down Set-Cookie "^mx_…=.*$" ""`
  (only the Harness cookies; Authorization and the app's cookies pass; checked with Caddy 2.11). `registry._save`
  writes back the entries `load()` refused (`_refused_servers`). Pasted key line:
  `no-agent-forwarding,no-X11-forwarding` instead of `restrict` (tunnels and pty keep working).
- #37 a card shows the branch when it is not `main`/`master`, or `git.detached`.
- #40 config `short_titles_model` (default false): without it `refine` = `heuristic()` only, no `claude -p`;
  with it the call adds `--disable-slash-commands`.
- #39 `idle_compact_tokens` default 200000 (was 60000).
- #38 `claude_auto_update` default false. Target = npm `stable` dist-tag (`depcheck.claude_stable`). `install_method()`
  from the realpath of the binary: native (`.local/share/claude/versions/`) -> `claude install <v>`, npm
  (`…/lib/node_modules/@anthropic-ai/claude-code/`) -> `<prefix>/bin/npm install -g --prefix <prefix>
  @anthropic-ai/claude-code@<v>`; else `tick()` -> "unsupported". `<state>/.claude-update.lock`: exclusive (no wait)
  around the update, shared by `runner.attempt` (`_claude_in_use`, waits at most 7 min) for the life of each claude
  process. A version that does not start is reinstalled back (`run_update(previous)`).
- #32 `claude_access` left out (crons unchanged since a51). `backup._apply`: holds only when `not _fresh_server()`
  (a session exists); stripped hooks saved to `<trash>/hooks-held.json`. `filesite.ASSETS` += md, jsonld, geojson,
  webmanifest, glb, gltf, bin, heic, ogv, mkv, opus, aac; `NOT_ASSETS` = memory.md / CLAUDE.md / AGENTS.md /
  CLAUDE.local.md; a topic page gets `MEDIA` files from `attachments/` (other files 403).
- #42 `export()` blanks with `_blank_secrets` (token-like value, or a `SECRET_NAME_RE` name: key, token, secret,
  pass, auth...), not every literal: plain settings survive a restore. `servers()` masks as in the PR.


## 2.0.0-alpha.66 - 2026-10-18

- `components/ui/sheet-drag.ts` (`useSheetDrag`, touch events, non-passive `touchmove`): swipe-down dismissal for
  `SheetContent` and mobile `DialogContent` through a hidden `DialogPrimitive.Close` (so `onOpenChange` runs as for
  any close). Starts from anything but fields / `[data-no-drag]` / `[role=slider]`, never while the scroll container
  under the finger is scrolled down; closes past 25 % of the height or at > 0.4 px/ms over the last 100 ms.
  `mergeRefs` in `lib/utils.ts`. Closing animations for Dialog / Sheet / AlertDialog (`animate-sheet-down`,
  `animate-overlay-out`, `animate-out`, `animate-sheet-{right,left}-out`).
- `lib/mobile-viewport.ts` (`useMobileViewport`, AppShell, `pointer: coarse` only): `html[data-kbd]` on field focus
  (zeroes `--tabbar-h`, `--safe-bottom`, `--safe-bottom-ui`; tab bar hidden), `--kbd-inset` / `--vvh` from
  `visualViewport` (bottom sheets: `bottom-[var(--kbd-inset)]`, `max-h` 92 % of `--vvh`), `scrollTo(0, 0)` when iOS
  leaves the document scrolled (keyboard closed, `visibilitychange`, `pageshow`).
- `lib/edge-swipe.ts` (`useEdgeSwipeBack`, standalone only, CSS `translate`): the mobile session overlay goes back.
- Tab bar 56 -> 52 px, `NavItem.short` (`nav.home`). Mobile menu: `MorePages` tiles (feature pages, `/x`, pinned pages).

## 2.0.0-alpha.65 - 2026-10-18

- Config default `git_page` = `False` (was `True`); `api/settings` fallback and `FEATURE_NAV.defaultOn` follow.
  Existing installs keep their value: `update_config` writes the merged config, so `git_page: true` is already in
  their `config.json` once any setting was saved.
- Removed `web/node_modules`, a dangling symlink committed by mistake in a64; `.gitignore` now says `node_modules`
  (without the slash, which only matched directories).

## 2.0.0-alpha.64 - 2026-10-18

- `maxxing/mcp.py` + `api/mcp.py` (`/api/mcp*`, bus topic `mcp`) + `cmd_mcp.py` (`maxxing mcp list|add|remove`) +
  skill `maxxing-mcp` + Settings section `mcp` (`sections/Mcp.tsx`). Claude Code stays the owner of the data
  (`.claude.json` user/local scopes, `.mcp.json`); writes through `claude mcp add-json|remove` with the turn env.
  States from a background `claude mcp list` per folder. OAuth = `claude mcp login --no-browser` on a pty
  (`login_start` returns the authorize URL, `login_finish` writes the pasted localhost redirect). `${KEY}` vault
  references are flipped to `expose` on add. Workspace rename hook moves `projects[<old>]` keys. Backup:
  `_maxxing/mcp.json` (literal secrets blanked), re-added on restore (`restore()` result gains `mcp`).
- `tests/fake_claude.py` handles `claude mcp list|add-json|remove|login`.

## 2.0.0-alpha.63 - 2026-10-18

- Plan limits from the turns: Claude Code prints `{"type":"rate_limit_event","rate_limit_info":{...,"unifiedWindows":
  {"five_hour"|"seven_day": {"utilization": 0..1, "resetsAt": unix}}}}` in stream-json (subscription only). The runner
  (`_observe`) keeps the last one in `<state>/claude-limits.json` via `claude_auth.record_limits`; `claude_auth.limits()`
  maps it (pct 0-100, a window past its reset = 0). `health.usage()` serves it first, always on, `source: "turn"`,
  `seen_at`; the experimental `/api/oauth/usage` (needs scope `user:profile`, refused for `claude setup-token`
  tokens) is only called with `usage_widget` on and turn limits older than `TURN_FRESH_S` (600 s) or missing.
- `resets_at` of `/api/usage` is always Unix seconds now (the endpoint's ISO 8601 is converted; it crashed
  `fmtDate` in Settings -> Stats, which also combined `dateStyle` with `weekday`). Dashboard widget formats it.
- Web: `shell/UsageIndicator` (under `HealthIndicator`, hidden when `available` is false), `useUsage(enabled, poll)`.

## 2.0.0-alpha.62 - 2026-10-18

- `infra/platforms.py` (Vercel, Netlify, Supabase, GitHub Pages; `VERIFIED` empty = all beta, written from the
  official OpenAPI documents) and `infra/dnsinfo.py` (DoH JSON `MAXXING_DOH_API`, cache `<state>/infra/dns.json`
  6 h, 80 names a refresh). `build.build(..., platforms=, dns=, watched=)`; locations `vercel|netlify|supabase|github`;
  domain details `hosted_by`, `www_hosted_by`, `unused_zone`, `added`; public A records feed the links when no zone
  was read; public name servers override an API zone that is not delegated. Registry `domains: []`.
- API `POST /api/infra/domains`, `/domains/remove`; `GET /api/infra` sources gain `vercel|netlify|supabase|github`
  (`label, beta, token_url, keys`). CLI `maxxing infra domain add|remove|list`; `status` lists the platforms.
- Web: kinds `pages` = "Hosted site", `worker` = "Function"; `providerName()`; AddDomain / RemoveDomain; platform
  rows + Documentation links (`/docs/infra`) in the overview; showcase `infra-domains`.
- Infra web files back to the project's code style (a prettier run had reformatted them in a60): no prettier in web/.

## 2.0.0-alpha.61 - 2026-10-18

- Two-step sign-in (`maxxing/twofactor.py`, see INTERNALS): `POST /api/auth/login` answers
  `{ok:false, two_factor:{challenge, expires_in}}` instead of the cookie when on and the browser has no valid
  `mx_device` cookie; `POST|PUT /api/auth/two-factor`, `POST /api/auth/two-factor/forget-browsers`;
  `two_factor` in Telegram `settings` (not in the public `/api/auth/state`). Config `telegram.two_factor`, secret `device_key`
  (cleared by `set_password`). Gateway callback kind `a:<id>:y|n`. CLI `maxxing 2fa status|off|forget-browsers`;
  doctor's Telegram check says it is on and points to `maxxing 2fa off` when Telegram reports an error.
  Web: `features/auth/TwoFactorWait` (polls every 1.5 s, code field, trust checkbox) on the sign-in page and in
  the "turn on" dialog (`TwoFactorRow`, in Settings -> Security and -> Telegram). Showcase `twofa`.
  Tests: `test_twofactor.py`, `test_telegram.py::test_two_factor_buttons` (real gateway, owner-only buttons).
- Cards of two-column lists (`GitPage` repositories, Infra resource rows and server cards) are `h-full` in their grid row.

## 2.0.0-alpha.60 - 2026-10-18

- `infra/connect.py`: Harness SSH key `<state>/ssh/infra_ed25519` (dir 700, made on first need). `auto_connect()` runs
  in `refresh()` after the providers: a running Hostinger VPS whose root keys (`GET /api/vps/v1/virtual-machines/<id>/
  ssh-keys`) include `~/.ssh/*.pub` or the Harness key, and whose IPs no registered server has, is registered (name =
  short host name, label "VPS Hostinger"); one look per VPS every 6 h (`<state>/infra/autoconnect.json`); no blind key
  tries (fail2ban). `connect_hostinger()` adds the key with `POST .../ssh-keys` (checked on a running VPS: SSH accepts
  it ~2 s later) then `ssh true` every 5 s up to 60 s. `connect_host()`: Harness key, then SSH defaults, else
  `need_key` + the line to paste. Providers: `hostinger_ssh_keys`, `hostinger_add_ssh_key` (the only provider write).
- Registry: servers get `label` (shown; `name` stays in the resource ids), `rename_server`, `free_name`. Build uses the
  label as the server resource name and puts `details.server`. `view()` adds `refresh_min` and `servers[].label`.
- API: `POST /api/infra/servers/connect|rename|remove` (API.md#infra). CLI: `maxxing infra server connect|rename`,
  `--label`.
- Web: `features/infra/Overview.tsx` (HowItWorks, hidden flag `mx.infra.howHidden` in localStorage; SourcesPanel;
  ServerCard), `ServerConnect.tsx` (ConnectVps, ServerSettings, AddServer), `locationLabel` uses the labels
  (`rememberServers`), showcase `infra-servers`; tabs row scrolls and the content grid is `minmax(0,1fr)` on phones.

## 2.0.0-alpha.59 - 2026-10-18

- Infra (`maxxing/infra/`: probe, providers, build, registry, caddy, actions; `api/infra.py`; `cmd_infra.py`; skill
  `maxxing-infra`; docs `docs/user/27-infra.md`, API.md#infra, INTERNALS.md#maxxing.infra). Config `infra_page`
  (false, restorable from a backup), `infra_refresh_min` (15). State `<state>/infra/{snapshot,rdap,backups}.json`,
  `stale`, `removed/`. Registry `<workspace>/infra.json`. Bus topic `infra`. Feed source `infra`.
- install.sh: Harness's Caddy block imports `/etc/caddy/maxxing-paths/*.caddy` before `reverse_proxy` (path sites);
  `maxxing infra site add` adds the line to older installs (validated, rolled back on error).
- Path sites: `handle_path` + `Content-Security-Policy: sandbox` without allow-same-origin (opaque origin: no cookie,
  no API - checked in Chromium: module scripts load thanks to `Access-Control-Allow-Origin *`, fetch to /api blocked,
  document.cookie empty). The existing `X-Maxxing` CSRF header already blocked cross-origin writes.
- Web: `features/infra/` (InfraPage, InfraBlock for ```infra, shared), nav `FEATURE_NAV` gets `defaultOn`, showcase
  `infra`, Settings -> Features switch. Workspace template: ```infra bullet, `maxxing infra` and `maxxing-infra` rows;
  help index row `27-infra.md`.
- Tests `tests/test_infra.py` (fake Caddy/psql/garage/Cloudflare/Hostinger, never the real system).

## 2.0.0-alpha.58 - 2026-10-18

- `gitview.tokens()`: all GitHub tokens (vault values matching `^(ghp_|gho_|ghu_|ghs_|ghr_|github_pat_)…` under any
  name, GITHUB_TOKEN/GH_TOKEN whatever the format, backup `github_token`; deduped by value). `github_repos` queries
  each in parallel and merges (best permission, `keys`, `accounts`; `accounts[]`, `errors[]` in the response);
  repository calls go through `_gh_repo` (tokens that listed the repo first). GitHub 403 -> `not_found`.
  Web: accounts bar with filter, refused keys callout, keys per repository. Test: two accounts, duplicate value,
  non-GitHub key, refused key, repo seen by one token only.

## 2.0.0-alpha.57 - 2026-10-18

- Catalog of optional extensions removed (Romain: app features belong to Settings -> Features, not to the
  Extensions page): `catalog.py`, `cmd_extensions.py` (`maxxing extensions`), `templates/catalog/`, routes
  `/api/extensions/catalog*` and `DELETE /api/extensions/{id}`, manifest `description` / `builtin`, `source`,
  `extensions.added`; `extensions.py`, `api/extensions.py`, the `/x` hub, `pages/ext/index.tsx`, Settings ->
  Extensions, `lib/queries/extensions.ts`, the `ext.*` texts, the extension docs and skill are back to 2.0.0a54.
  A leftover config `extensions.added` is ignored.
- Git page = route `/git` (`features/git/GitPage`, `<Page>`), config `git_page` (default true, settings API,
  restorable from a backup), row in Settings -> Features; nav: `useNav()` in `components/shell/nav.ts` adds
  `FEATURE_NAV` items before Settings (sidebar, palette, `g b` shortcut, shortcuts dialog; not the mobile tab bar).
  ```git blocks link to `/git?repo=` when `git_page` is on. Showcase `git` routes to `/git`.

## 2.0.0-alpha.56 - 2026-10-18

- `maxxing/gitview.py` + router `api/git.py`: `GET /api/git/repos|graph|commit|pulls` (read-only; local clones
  under the files root, GitHub through vault `GITHUB_TOKEN`/`GH_TOKEN`). Tests `test_gitview.py` (real git repos in
  tmp + fake GitHub on `_conn_helpers._Server`); `_org_helpers.ORG_ROUTERS` gains `git`.
- Catalog reworked (Romain: catalog extensions are app features shown or not, no download/copy): no more copy,
  `.catalog.json`, `update` route / CLI or `modified`; `add` = config `extensions.added`, loaded from
  `templates/catalog/<id>/` by `extensions._dirs()`; `remove` of a catalog extension = dropped from `added`.
  `needs.optional`. Manifest `builtin` (catalog only): page drawn by the app (`pages/ext/builtin.ts` ->
  `features/git/GitPage`), no page.js. First catalog entry: `templates/catalog/git`.
- Web: `features/git/` (GitGraph lane layout + SVG, CommitDetail, GitBlock, GitPage, GithubMark),
  `lib/queries/git.ts`, ```git in `components/ui/markdown.tsx` (React.lazy: avoids the ui <-> features cycle),
  showcase `git`. Fixed: `useToggleExtension` had `errorToast: false` (a55 edit landed on the wrong hook).
- Workspace template CLAUDE.md: "Git" bullet under "Answers shown in the UI" (upgrade note adds it to existing
  workspaces); help index: `26-git.md`.

## 2.0.0-alpha.55 - 2026-10-18

- Extension catalog: `templates/catalog/<id>/` (empty for now, README), module `maxxing/catalog.py`
  (`list_items`, `add`, `update(force)`, `CatalogError`), marker `.catalog.json` `{catalog, version, added,
  files:{rel: sha256}}` in the added copy. Routes `GET /api/extensions/catalog`, `POST
  /api/extensions/catalog/{id}/add|update` (`409 already_added|exists|modified`, `404 not_found|not_added`),
  `DELETE /api/extensions/{id}` (trash + unpin, `extensions.remove`). `GET /api/extensions` gains `description`
  (manifest, str or per language) and `source` (`workspace`|`catalog`). CLI `maxxing extensions
  list|add|update|remove` (`cmd_extensions.py`). Skill `maxxing-extension`: check the catalog first.
- Web `/x` (`pages/ext/hub.tsx`): sections "Your pages" (source workspace, enabled pages + "ask Claude" tile that
  opens a new session in `system/harness` with the prompt typed) and "Added extensions" (source catalog: open /
  update with confirm on `modified` / remove; then the catalog items not added, with `needs.keys` and `conflict`).
  Settings -> Extensions: "Catalog" badge. Catalog query lives under `qk.extensions` (refreshed by the bus topic).

## 2.0.0-alpha.54 - 2026-10-18

- `SidebarExtensions`: pinned pages no longer indented (`pl-5` removed) and icon back to `size-[18px]` like every
  sidebar entry (the indent + `size-4` made the icons look broken).

## 2.0.0-alpha.53 - 2026-10-18

- Connexxion (PR #26, merged into a50 by mistake) removed; it lives on FEU's branch `feat/connexxion`. Gone:
  package `maxxing/connexxion/`, routers `connexxion` / `peer` / `cxagent`, `cmd_connexxion`, config defaults
  `connexxion`, bus topic `connexxion`, `profile_changed` hook in PUT `/api/settings/profile`,
  `spawn.UNTRUSTED_DENY` + `settings_args(allow, untrusted)` (back to `settings_args(cfg)`), fake_claude plan /
  condense replies, `test_connexxion.py`. Web: page, features, queries, keys, types, settings section, nav entry +
  mobile tab (tab bar back to `grid-cols-6`, `NavItem.short` dropped), showcases, `Markdown showHtml`,
  `.mx-msg-in/.mx-typing/.mx-glow`, 320 i18n keys per language. Docs: user page 26, API / INTERNALS / DESIGN
  sections, README. Kept from the same branch: the profile pseudo, PRs #24 and #25. Leftovers on existing
  installs (`<state>/connexxion`, config / secrets key) are ignored; the upgrade note offers to delete them.

## 2.0.0-alpha.52 - 2026-10-18

- Web only: `/x/:id` header gets a pin toggle (`usePinExtension`, same PATCH `/api/extensions/{id}` `{pinned}`).
  `SidebarExtensions`: the `/x` entry is always first (count badge = unpinned pages, hidden at 0), pinned pages
  listed below it, indented. No API or config change.

## 2.0.0-alpha.51 - 2026-10-17

- `crons._job_env`: `spawn.base_env()` (PATH with `claude`, HOME, `CLAUDE_CONFIG_DIR` when `claude_dir` is set) +
  `spawn.auth_env()` (stored Claude token / API key + exposed vault keys); falls back to os.environ + vault.
  `test_shell_job_gets_the_claude_turn_environment`.

## 2.0.0-alpha.50 - 2026-10-17

- Integration of the stacked PRs #24 (round 2), #25 (media actions) and #26 (Connexxion) on top of main a46-a47
  (their a46/a47/a48 renumbered a48/a49/a50). Security review fixes: a turn of a session with `source=connexxion`
  gets extra deny rules `Edit(//<ws>/**/{.claude/**,.mcp.json,CLAUDE.md,memory.md})` (`spawn.UNTRUSTED_DENY`, peer
  text cannot plant settings/hooks/MCP/instructions for later turns); peer `size` parsed with `service._int`
  (no 500); group ids from peers must match `g-[A-Za-z0-9_-]{1,18}`. Open (medium): DNS re-resolution of a
  paired peer on each call (SSRF to private ranges), pairing rate limit keyed on the proxy IP when the proxy is
  not on loopback, accepted peer skills may overwrite a local skill of the same name.

- Profile: config `profile` {name ≤32, color in `PROFILE_COLORS`, emoji}, `GET/PUT /api/settings/profile` (bus
  `profile`); web `features/profile/Avatar.tsx` (`Avatar`, `PersonChip`), user bubbles show the pseudo; Telegram
  mirrors `🖥 <b>name</b>`.
- Connexxion: package `maxxing/connexxion/` (`protocol` pairing / keys / signatures / address checks / transport,
  `store` state files, `service` links, events, outbox, inbound, worker, `work` AI generation + runs + agent API,
  `share` files / skills / sessions, `groups` hub relay). Routers `connexxion` (cookie), `peer` (public, signed,
  `/api/peer/v1/*`), `cxagent` (loopback + run token). CLI `maxxing connexxion` (agent commands). Config
  `connexxion` (off by default). State `<state>/connexxion/{links.json, threads/, audit/}` 0700/0600; keys, invites
  and joins in secrets.json `connexxion`. Bus topic `connexxion`. Protocol 1, `CAPS` announced in `hello`.
- Pairing: 80-bit code, never sent; B proves it (`HMAC(code, "mx-pair|b_nonce|url")`), A answers with a link id,
  B polls `pair/status` with `poll_key`; key = `HMAC(code, "mx-key|a_nonce|b_nonce|link")`, fingerprint
  `sha256(key)[:8]`. Requests signed over `METHOD\nroute\nts\nnonce\nsha256(body)`, ±300 s, nonce replay cache.
- Events: one JSONL thread per link, `_sanitize` per kind (limits, ids `[A-Za-z0-9_-]{1,40}` kept as received),
  inbound side forced to the peer's, cards never replaced by id, at most 100 open cards from a peer, 64 MB thread
  cap (then control events only), 600 requests/min per link, NaN / Infinity refused (`_parse`), `resume` only by
  who paused. Outbox per link with backoff (≤ 300 s), flushed by the worker every 3 s or on `wake()`, each link in
  its own pool thread (8); a response slower than 64 KB/s after 30 s is cut (`too_slow`).
- Plans: version + hash of the canonical JSON; `accept` carries the hash; a new version supersedes; runs need an
  agreed plan with the same hash. Runs: `mine` / `theirs` / `balanced` (`states` per executor side), budget
  (turns / tokens per day, A2A per hour per run and direction) checked before start and before every injected
  message. Agent sessions: source `connexxion`, permission mode from config (never bypass), allow rule
  `Bash(maxxing connexxion:*)`, env `MX_CX_RUN/LINK/TOKEN/URL` (token stored as sha256).
- Peer text reaches Claude only inside `<<<peer-<random tag> … peer-<tag>>>>` with an "untrusted" header; the plan
  of a run inside `<<<plan-<tag>`. Web `PeerMarkdown`: no images, raw HTML shown as text (`Markdown showHtml`).
- Files: offered from files_root / workspace only (not secrets.json, the state dir, hidden paths), sha256 + size
  checked on receipt, saved in `<topic>/connexxion-files/`, receiver's `max_file_mb` enforced. Skills / extensions
  bundled as text files (`clean_bundle`), extension disabled before its files are written.
- Groups: the creator's server is the hub (relays queued per member), members tag their posts with a `cid` so a
  hub cannot post "as" them; ≤ 5 pending invitations per link; not end-to-end encrypted (the hub reads).
- Web: page `/connexxion[/<id>]` (`pages/connexxion`, `features/connexxion/*`), nav entry with pending badge (mobile
  tab only when enabled), Settings → Connexxion / Profile, showcases `connexxion`, `connexxion-plan`,
  `connexxion-a2a`. Thread rows memoized (`EventRow` signature, `PeerMarkdown` memo); first page 120 events, a
  refetch keeps the earlier pages loaded.
- Composer toolbar is an `@container`: under 24rem `ModelPicker` hides the current model when a switch is pending
  (`→ next` stays) and `PlanChip` shows its icon only (`aria-label` kept); both `whitespace-nowrap`.
- Measured (two servers on one host): message A -> B 27 ms median; routes 4-15 ms with a 5,000-event thread;
  idle worker 0.5 % CPU; 0 janky frames with live arrivals on a 5,000-message thread.

## 2.0.0-alpha.49 - 2026-10-17

- Video quality: `maxxing/videos.py` (ffprobe info cached per path+mtime+size, one-worker encode queue with
  `-progress pipe:1`, cache `<state>/videos` 0700 trimmed to 4 GB by atime) + `GET /api/files/video`,
  `POST /api/files/video/prepare`, `GET /api/files/video/stream` (docs/dev/API.md). Web:
  `features/files/videoQuality.ts` (`useVideoQuality`: choice in localStorage `mx-video-quality`, Auto = server's
  `auto`, missing copy prepared once per player, polled every 1.5 s while one is busy) and `MediaPlayer`
  (quality button + in-player menu - not a portal, so it shows in full screen -, a source switch resumes at the
  same time / play state, a failing copy falls back to the original). Showcase `video-quality`.
- Player speed: `SPEEDS` 0.5-4 (was 0.75-2, click cycled), the speed button opens a `PlayerMenu` (shared with the
  quality menu, `MenuRow`; the audio card drops it below itself, or above when the screen has no room), keys `<` / `>` step; the speed survives a
  quality switch.
- `features/files/download.ts`: `downloadFile(path, version)` / `downloadProps(path, version)` on every download
  link (viewer, preview, Files listing / file menu, PDF bar, info card). Images and PDFs: `fetch` of the URL the page
  displays (`/api/files/raw?path=&v=`, same cache entry: 304 at most) -> blob -> object URL -> `<a download>`; the
  former `?download=1` URL was a separate cache entry, so the whole file crossed the network again. Other kinds:
  the native `?download=1` link (streamed, browser progress). Middle / modifier clicks keep the plain link.
- `pages/sessions/FileMenu.tsx`: capture-phase `contextmenu` on the thread (`[data-mx-file]`, `a[href^="#mx-file="]`,
  absolute paths only; wins over the user-message menu) -> DropdownMenu at the pointer (portal, fixed 0-size
  trigger, no focus return): Open / Download (`downloadFile`) / Quote / Copy path. Quote = `fileQuote(path)` =
  `📎 /abs/path` in the composer quotes (sent as `> 📎 /abs/path`), `quotedFile(q)` recognises it; `QuotedFile`
  renders it (thumbnail or icon + name, opens the viewer) in the quotes card and in the sent bubble. Showcase
  `file-menu` (centered card).

## 2.0.0-alpha.48 - 2026-10-17

- Turn env (`spawn.claude_env`): `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` unless set (config `claude_quiet_start`,
  default true; measured 0.87 -> 0.52 s to `system/init`, prompt 18 998 -> 18 101 tokens, `ephemeral_1h` cache kept);
  `CLAUDE_CODE_AUTO_COMPACT_WINDOW` = `spawn.compact_window(cfg)` = threshold (>= 100k) + `COMPACT_WINDOW_MARGIN`
  45 000, capped 1M (Claude Code compacts ~43k below its window: compacted at ~57k with a 100k window). Both in
  `TUNING_ENV`: a value set for the service wins.
- `sessions/tokenreport.py` + `maxxing sessions token-report [--days] [--json]`: regex pass over
  ~/.claude/projects/*/*.jsonl (dedup by message id, json only for tool_result lines; 5 568 calls in 1.9 s),
  buckets, mid-session rewrites (> 30k written: idle > 1 h / model switch / other), tool result characters (images
  counted 6 000 chars each), `simulate(sessions, threshold, inside_turns)` (growth replayed, compaction -> 45k).
- Runner: `Attempt.t0/start_s/first_s` -> meta `latency` [[start_s, first_s], ...] (`LATENCY_KEPT` 20);
  `stats.compute()["latency"]` = medians over all sessions. index.html gzipped (cached per mtime) when no
  X-Forwarded-For and gzip accepted. Doctor `memory` (/proc/meminfo: WARN when RAM <= `SMALL_RAM_MB` 2600 and swap
  < 512 MB, fix = 2 GB swapfile).
- Latency: stream `POLL_RUNNING_S` 0.25 -> 0.1 (event shown 117 -> 69 ms median, max 233 -> 92 ms; one stat of the
  log + meta per tick); turn-end watcher passes every `WATCH_RUNNING_S` 0.25 while a session runs (turn end seen
  0.57 -> 0.14 s median, max 0.89 -> 0.17 s; unchanged running sessions re-read only every `RUNNING_RECHECK_S` 1 s);
  run lock retry `store.LOCK_RETRY_S` 0.2 -> 0.05. `useSessionEvents` (unused) removed.
  Not kept: snippets only for the shown rows in search (query 10 -> 4 ms for one word, no gain on others; the
  session refresh dominates) and skipping that refresh for 1 s (a message just written would not be found).
- i18n: `en` is a lazy chunk like `fr` (`import type { en }` for TKey; `loadLanguage` falls back to English when the
  active dictionary fails). The preloaded `code-block` chunk shrank 99.7 -> 18.3 kB (it carried en.ts): first load
  226.4 -> 205.2 kB br (firstload.py); a French page fetches only fr (Puppeteer).
- `ModelPicker` (`contextTokens` prop, `SWITCH_WARN_TOKENS` 50k): confirm() before a switch to a model that does
  not match `real_model` (`matchesModel`; "" = the default model); cancel = no PATCH (Puppeteer checked).
- Permissions: `effective_mode(meta, cfg)` in runner = `meta.permission_mode` (set by a cron, `store.new_meta(...,
  permission_mode)`, a reused cron session is updated by `crons.store_mode`) > `workspace.topic_permission_mode(path)`
  (`topics/<t>/.maxxing.json`, `PATCH .../topics/{t}` `permission_mode`, now in `Topic` and in the backup) > config.
  Cron field `permission_mode` ("" | bypass | acceptEdits | default, `invalid_permission_mode`).
- `spawn.settings_args(cfg)`: `--settings {"permissions":{"deny":[...]}}` on every turn - `Read/Edit(//<STATE>/secrets.json)`
  and `Read/Edit(//~/.ssh/**)` when `protect_secrets` (default true; `GET/PUT /api/claude/...`), plus config
  `claude_deny`. Checked live (Haiku, root, bypass): Read and `cat` refused, `python3 -c open()` not - documented as a
  speed bump. Absolute paths need `//` in Claude Code rules (`/x` is relative to the project).
- fake_claude: parses `--settings`, records the two new env vars.
- Doctor `caddy_site` (`cmd_core.check_caddy_site`, `CADDY_SITE` / `MAXXING_CADDY_SITE`): WARN on
  `X-Frame-Options "DENY"` (replaced the app's SAMEORIGIN: the PDF iframe in Files was refused) or a `max_size` below
  `upload_max_mb`; fix = two `sed` + `systemctl reload caddy`. install.sh `max_size` 500MB -> 2100MB
  (`CADDY_BODY_MB`, test keeps them equal). Upgrade note 2.0.0a48 step 1 (asks first).
- `security.MIN_PASSWORD` 12 (setup, change, `maxxing password`; web `pages/auth/strength.ts` MIN_PASSWORD, score
  steps moved to 16/20). `/api/auth/password`: `begin_attempt/end_attempt("pw:" + client_key)` around `_verify`.
- `app._HEADERS` + `permissions-policy` (camera, geolocation, payment, usb, serial, hid, bluetooth, midi, sensors,
  display-capture off; `microphone=(self)` for voice).
- State files 0600: `config._atomic_write` (paths under STATE, no explicit mode), session logs (`store._private`
  opener), new feed.db / search.db created 0600 before sqlite opens them (WAL/SHM inherit it);
  `config.tighten_state()` at startup (top of STATE, sessions/, crons/, telegram/: group/other bits dropped).
- `maxxing/depcheck.py` (stdlib only): `osv_scan()` on server/uv.lock, web/package-lock.json and
  STATE/tools/remotion/package-lock.json (OSV querybatch, 500 per call); `claude_latest()` (npm registry) +
  `claude_behind()`; `skill_listing(roots)`. Doctor: `claude_version` (INFO, skipped with --offline),
  `skill_listing` (INFO past `SKILL_LISTING_BUDGET` 8000 chars), `deps` (only `--deps`; WARN when vulnerable, INFO
  when OSV is unreachable). Here: 799 packages clean, Claude Code 6 releases behind, 155 skills / 26 477 chars.
- web/package.json `overrides: {katex: ^0.18.2}`: mermaid 11.17 asks ^0.16 (GHSA-238p-pmpm-9mq7, fixed in 0.18.2);
  0.18.10 installed, flowchart math + sequence diagrams checked in Files (Puppeteer, no console error). Drop the
  override when moving to mermaid 12 (katex ^0.18).
- Web deps (no advisory, minor/patch): react/react-dom 19.3.1, @tanstack/react-query 5.104.3, lucide-react 1.58,
  14 @radix-ui packages (dialog 1.3, dropdown-menu 2.2, select 2.4, tooltip 1.4...). Checked: tsc, build, Puppeteer
  smoke (Settings select + switch, tree context menu, dialogs, cron editor; no console error). OSV on all lockfiles
  (785 packages): clean. fastapi 0.143.3 not taken: `uv lock --upgrade-package fastapi` also re-resolved
  onnxruntime and added pyreadline3.
- templates/remotion/package-lock.json (the lock of the working install, 289 packages, OSV clean) + install.sh
  `npm ci`.
- backup.LEAKS: + Stripe key (`sk|rk_live|test_`), Stripe webhook secret (`whsec_`), Google API key (`AIza` + 35),
  JSON web token (3 base64url parts), password next to its label (8+ chars mixing letters and digits, not in
  `<>`/backticks/quotes). Run on the real workspace here (1 508 files): no false positive.
- Diagrams in the file viewer: `components/ui/diagram.tsx` gives each ```mermaid block a viewer path
  `mx-diagram:<djb2 hash of the code>` (`DIAGRAM_PREFIX`, code kept in a module map, `diagramCode(id)`), carried as
  `data-mx-file` on the figure so `threadFiles` puts it in ← / → order. Click: `openFileViewer(id, threadFiles)`
  inside a thread, else inserted after the current viewer item. `useDiagramSvg(code, debounce)` shares the render
  queue and keeps the last 50 SVGs (the viewer reuses the one drawn inline). `Viewer.tsx` `DiagramPane` (Preview /
  Source, copy) and `viewers.tsx` `DiagramView` (fit up to 2x from the viewBox, `ZOOMS` steps, centre kept,
  mouse-drag pan, Ctrl+wheel, + / - / 0); the old zoom `Dialog` is gone. `threadFiles` and `FILE_HREF` moved to
  `features/files/viewerStore.ts` (re-exported by `pages/sessions/util.ts`).
- Inline audio: `audioPaths()` (util, max 4) -> `MediaPlayer kind="audio"` under the answer and in `AttachmentStrip`
  (wrapped in `data-mx-file`); `MediaPlayer` `onOpen` makes the name open the viewer; both player roots carry
  `data-media-player` (the viewer's ← / → guard already looked for it).
- `viewers.tsx` `usePanZoom(box, zoom, onWheel)`: native non-passive wheel (Shift lets it scroll; ~50 px of delta per
  step), `wheelZoom()` = next multiple of 5 % (0.05-8), `capture(point?)` before a zoom change keeps that point of
  the `[data-zoomable]` element under the same spot (layout effect on `zoom`), mouse-drag pan with grab / grabbing
  cursor. Used by `ImageView` (was: Ctrl + wheel through `ZOOMS`, no pan, zoomed image stuck top-left - now `m-auto`
  in a flex scroller) and `DiagramView`; +/- keys and buttons keep the `ZOOMS` steps, centred.
- Look on the sign-in page: config `look` {theme, accent, tint} (`api/settings.look()`, `PUT /api/settings/look`,
  pydantic `LookIn`), returned by the public `/api/auth/state`. Web: `ui.lookChosen` (set by setTheme / setAccent /
  setTint; true for browsers saved before it when they stored a theme), `adoptLook()` in Root when not chosen,
  `AppShell.useShareLook` PUTs 600 ms after a change (and once when the server has none). index.html applies the
  server look as soon as the early auth check answers (same rule), before React.
- What's new "Show me": a CHANGELOG bullet ending with `[Show me](#show:<id>)` -> button (WhatsNewDialog `onLink`)
  that closes the dialog and runs `useTour.start(SHOWCASES[id])` (`features/whatsnew/showcases.ts`). The tour takes
  an optional step list (`showcase`): no closing card, `tourDone` untouched, a single step shows "New", empty
  `targets` = centered card, `before(ctx)` / `cta` + `after()` (the diagram demo opens the viewer after the card
  closes, so the dialog focus trap never fights the tour's). Unknown ids are stripped and the label translated (`showLinks`);
  `changelog.strip_show` drops the links from `maxxing update` notes. Showcases: look, diagram, topic-permissions.
- Review fixes: `spawn.deny_rules` always denies `Edit(//<workspace>/**/.maxxing.json)` (a topic in a stricter mode
  could otherwise write its own mode back to bypass), so `--settings` is now on every turn; `claude_deny` given as a
  string is one rule; side questions (`aside`) get the deny rules too. Backup "password" pattern skips `$VARS`, links
  and password-manager names. Web: i18n falls back to any loaded dictionary (no raw keys while a new language
  downloads); main.tsx adopts the server look before binding the store to the document (no flash, 400 ms max);
  `usePanZoom` re-attaches its wheel listener when the box is re-created, lets sideways swipes scroll and centres
  keyboard / label zooms; diagram codes kept only once drawn (last 200); → on a showcase's last card runs its
  action; a finger on a zoomed view (`data-zoomed`) pans instead of changing file.
- `useHotkey('+')`: `'+'.split('+')` gave an empty key, so '+' never matched; now matched on `e.key` whatever Shift.

## 2.0.0-alpha.47 - 2026-10-17

- `cmd_keys.py` (registered in `commands.py`): `keys list [--json] | get NAME | set NAME [--note] [--no-expose]
  | delete NAME` over `maxxing.vault`. `set` reads stdin (no value in argv / `ps`), a new key is exposed by
  default, an update keeps note + exposure (`put(expose=None)`). Exit codes: get missing 1, invalid 2.
  `tests/test_cmd_keys.py`. Docs 11 + 17, workspace CLAUDE.md template command table.

## 2.0.0-alpha.46 - 2026-10-17

- `search._index_files(con, deep)`: memory files read at their known places (`_layout`: root, projects/*,
  projects/*/topics/*) outside the caps, plus deeper ones met by the walk; other files per bucket (topic; project
  minus topics/; root minus projects/) with `per = clamp(MAX_FILES // buckets, BUCKET_MIN 50, BUCKET_MAX 1000)`,
  `MAX_SCAN_ENTRIES` 20 000 per walk, global `MAX_FILES`; walks return at the cap (the old `break` only left the
  file loop, os.walk went on over the whole tree). TEXT_EXT loses .json/.csv/.tsv/.xml/.svg.
- `refresh(full, deep)`: `deep=None` (background loop) walks the files only every `FILES_EVERY_S` = 600 s, memory
  files every pass; direct calls default to `deep=True`. Rows outside the rules are dropped on the next walk;
  meta `file_rules` (`FILE_RULES = "2"`): when it changes and rows went away, `fts rebuild` + VACUUM once
  (measured on a 466k-file workspace: 19 384 rows dropped, 448 MB -> 58 MB, walk 0.5 s, light pass 8 ms).
- `stats()` adds `files_walked_at` and `files`. Tests: big project vs last project's memory, walk stops at the
  cap, data rows dropped + compaction, background light pass.

## 2.0.0-alpha.45 - 2026-10-17

- `install.sh`: `choose_claude_dir` (after the access / restore questions). CLAUDE_DIR set -> kept; an existing
  installation (`<state>/config.json`) -> its `claude_dir`, never asked; otherwise, when `~/.claude` is in use
  (sign-in, skills, CLAUDE.md or conversations in `~/.claude/projects`, now detected too) -> question 1 own folder
  `~/.claude-harness` (default, also without a terminal) / 2 share. Install guide PDF and docs/user/02 updated.

## 2.0.0-alpha.44 - 2026-10-17

- Config `claude_dir` ("" = `~/.claude`) + `config.claude_dir()` (config -> env `CLAUDE_CONFIG_DIR` -> `$HOME/.claude`).
  `spawn.base_env()` sets `CLAUDE_CONFIG_DIR` when configured (runner units and CLI-started crons read the same
  config, nothing else to forward). Replaces every `HOME/.claude` path: skills target, `settings.json`
  (cleanupPeriodDays), credentials (doctor, claude_auth), transcript move. `maxxing init --claude-dir`, installer
  `CLAUDE_DIR` (created 700, preflight suggests it when `~/.claude` is already set up). Checked with the real CLI:
  only its own skills + CLAUDE.md are loaded, transcripts go to `<dir>/projects`. Tests
  `test_init_claude_dir_keeps_home_claude_untouched`, `test_default_claude_dir_is_home_claude`.

## 2.0.0-alpha.43 - 2026-10-17

- New settings section `updates` (after `system`, `sections/Updates.tsx`): `GET /api/system/changelog?limit=500`
  (max raised from 50 to 500), search, "Installed" badge. The generated docs page `changelog` (a40) is removed
  from the in-app docs; the member area keeps its "All updates" page (no Settings there). What's new dialog links
  to `/settings/updates`. `test_all_updates_in_settings`.

## 2.0.0-alpha.42 - 2026-10-17

- Tree: session rows are draggable (not while running or queued); drop targets = topic rows and session rows of
  another topic (`useSessionDrop`, module-level `draggedSession` since dragover cannot read the data) -> the same
  `PATCH /api/sessions/{id} {path}` as the column's topic picker (`useMoveSessionTo`: expand the destination,
  toast). Merged with the topic reorder handlers (`mergeDnd`).

## 2.0.0-alpha.41 - 2026-10-17

- Sessions strip wheel handler: listens on `document` (contained in the strip), turns `scroll-snap-type` off while
  wheeling and back on 180 ms after the last event (a programmatic `scrollLeft +=` of a few px was snapped back to
  the column, so the a35 handler scrolled nothing). `deltaMode` lines handled.

## 2.0.0-alpha.40 - 2026-10-17

- `api/docs.py`: generated page `changelog` ("All updates", section Reference, order 9000) = CHANGELOG.md of the
  code (title and intro replaced); part of the docs cache signature and of the full-text search. Same page in the
  member docs (`cloud/scripts/build-docs.py`).
- `tests/test_docs.py::test_every_version_is_documented`: the current version must head CHANGELOG.md (newest
  first) and CHANGES.md, and every version needs `docs/upgrade/<version>.md`. Rule added to the repo CLAUDE.md.
- Help topic template: index line for CHANGELOG.md.

## 2.0.0-alpha.39 - 2026-10-17

- New module `smartupdate.py` (see INTERNALS): preflight in a temporary git worktree, verification, after-update
  hook, assist / fix sessions. State files `update/{preflight,report,after}.json`.
- API: `GET /api/system/update/preflight`, `POST /api/system/update/{assist,verify,fix}`, `GET
  /api/system/update/report`; `/api/system/version` gains `report` and `after`; `POST /api/system/update` runs
  `maxxing update --smart`.
- CLI: `maxxing update --preflight [--json] | --verify [--json] | --smart`; `maxxing custom save --check`,
  `maxxing custom check ID CMD`; customization trailer `Check:` + `customizations/checks.json`.
- `cmd_update`: edits under `web/` are stashed (`git stash push -u -- web/`) instead of aborting the update.
- Extensions: `EXT_API = 1`, `EXT_API_MIN = 1`; manifest `api` (default 1), out of range = load error; `info()`
  has `api`. Shipped manifests say `"api": 1`; test `test_shipped_extensions_still_load`.
- Config `update_auto_notes` (default true). Env `MAXXING_AFTER_UPDATE_DELAY` (default 15 s).

## 2.0.0-alpha.38 - 2026-10-17

- Dashboard defaults: `BUILTINS` order activity, server, day, tasks, usage, crons, backup, telegram, shopify,
  `customize`; with no saved order, `widgets.default_hidden()` (crons, backup, telegram, shopify unless
  `shopify.configured()`). `customize` sorts after extension widgets until the user places it. Reserved id.
- New built-in `customize` ("Make it yours"): examples linking `widgets.ask_href(prompt)` =
  `/sessions?path=<update topic>&new=1&prompt=...`. Empty states: activity (`_first_steps`), tasks (no open
  task), day (`_next_run_blocks`: next run within 8 days, or a link to ask for one).
- Card `list` block: `grid?: bool` (tiles, container-query columns) and item `emoji?`.
- Sessions URL `&prompt=` (with `new=1`): `prefillDraft()` writes the new column's draft before it mounts and
  fires `mx-draft` for a mounted composer; an untouched earlier prefill is replaced (`mx-prefilled:<key>`).
- Extensions: manifest `name` may be `{lang: name}` (`Extension.label()`); page `ctx.lang`.
- Default extension `templates/workspace/extensions/pages/` (page + tiny api.py giving the topic for the
  examples). `cmd_core._seed_unit` treats `extensions/<id>` as a seeded unit: copied once, never re-created
  after the user deletes it.

## 2.0.0-alpha.37 - 2026-10-17

- `packs.install`: always a new project (`_free_name` -> `<p>-N`), "# Project <p>" title lines of the root
  CLAUDE.md/memory.md renamed, job names suffixed " (<project>)" for copies; result gains `project`.
- Virtual pack `basics` (first in `list_packs`, `basics: true`): copies the missing files of
  `templates/workspace/projects` (ignores `install.json` `seeded`, it is an explicit request; no jobs).
- UI: Settings cards always show Add (no "Added" state); onboarding hides `basics`.

## 2.0.0-alpha.36 - 2026-10-17

- `SystemSection`: `VersionCard` first, then health, services, logs.

## 2.0.0-alpha.35 - 2026-10-17

- Workspace order: `PUT /api/workspace/order {names}` (projects, stored in `projects/.order.json`
  `{"projects": [...]}`, added to the backup allow-list) and `PUT /api/workspace/projects/{p}/order {names}`
  (topics, key `topics` of `projects/<p>/.maxxing.json`, next to the emoji). Unlisted names follow A-Z, unknown
  ones are dropped; renames keep the position. `workspace.project_names()` / `topic_names()` drive `tree()`
  and `list_topics()`. Writes call `bus.invalidate("workspace")` only (no Telegram rename callbacks).
- Tree: native HTML5 DnD (`useReorderRow` in `pages/sessions/Tree.tsx`, MIME `application/x-mx-project` /
  `application/x-mx-topic-<project>` so topics never change project), off while the tree is filtered.
- Sessions strip: non-passive `wheel` listener scrolls the strip on horizontal deltas unless an inner element
  can still scroll sideways (threads use `overscroll-contain`, which swallowed them).
- Settings sections order: general, system, stats, then the rest.

## 2.0.0-alpha.34 - 2026-10-17

- Settings section id `projects` -> `packs` (route `/settings/packs`), label "Starter pack", placed before `docs`.
- `FeedSettingsCards` returns a `grid gap-6` wrapper instead of a fragment (it is one child of `SectionStack`).

## 2.0.0-alpha.33 - 2026-10-17

- Starter packs: `templates/packs/<id>/` (`pack.json` {id, project, emoji, title/description {en, fr}, topics, crons}
  + `project/` copied to `projects/<project>/`). `maxxing/packs.py` (`list_packs`, `install`: missing files only,
  rendered like the workspace templates, emoji set when the project has none, jobs created disabled once by name),
  `api/packs.py` (`GET /api/packs`, `POST /api/packs/{id}/install`), `cmd_packs.py` (`maxxing packs list|add`).
  Web: `features/packs/PackPicker.tsx` (`PackCards` for Settings -> Starter pack, `PackChooser` for the onboarding
  "workspace" step: all / choose / none, then optional own project), `usePacks` / `useInstallPack` (key under
  `workspace`).
- Default workspace: `general/inbox` (absorbs tasks + subscriptions), `system/{tutorial,help,harness}` (tutorial =
  the 4 lessons; help absorbs server; harness absorbs update + extensions + packs). Removed templates:
  `system/{update,server,tasks,accounts,extensions}`, project `tutorial`. Default jobs: Morning tasks runs in
  `projects/general/topics/inbox`; Renewal reminder is no longer a default job.
- Older workspaces keep their layout: `copy_templates` does not seed `system/tutorial` / `system/harness` when
  `system/update` or the `tutorial` project exists. `cmd_core.update_topic()` (system/harness, or system/update on
  older workspaces) is used by every "open the topic ..." message and feed link; the Settings -> System button
  follows the same rule; the tutorial entry (`useTutorialHref`) finds `system/tutorial` or the old first lesson.

## 2.0.0-alpha.32 - 2026-10-16

- Costs: Claude's `result.total_cost_usd` is the running total of the Claude thread. `store.turn_cost(total, prev)`
  (increase, or the total when it went down) with `store.thread_prev_cost(meta, csid)`; the runner records
  `meta.thread_cost = {csid, total}`, adds `mx_turn_cost` to the logged result line (normalize uses it for
  `result.cost_usd`) and counts that in `cost_usd` / `days`; side questions (`aside`) too. `sessions/costfix.py`:
  one-time repair at startup (`cost_v` 2 in the meta; new sessions are created with it): recomputes cost and daily
  costs from the log, rewrites result lines with `mx_turn_cost` (atomic, run lock; running sessions retried every 2 min
  until idle). Fake Claude (tests) now reports a running total too.
- Automatic compaction: config `auto_compact_tokens` (400000; 0 = off; raised to `AUTO_COMPACT_MIN` 100000),
  `GET /api/claude/status` + `PUT /api/claude/settings`; `Runner._auto_compact` puts a `compact` item (`auto: true`,
  `SUMMARY_PROMPT`, now defined in runner.py) at the head of the queue after a user/seed turn whose
  `context_tokens` reached it - not for crons, a plan waiting for approval or when a compact/handoff is queued.
  Summary turns keep the session's model (another model would miss the prompt cache and cost more).
- `spawn.BASH_OUTPUT_MAX` = 15000 -> `BASH_MAX_OUTPUT_LENGTH` for turns unless set (also in `TUNING_ENV`).
  Template CLAUDE.md: section `## Saving tokens` (upgrade note 2.0.0a32 adds it).
- `TAIL_EVENTS` 200 -> 100 (biggest session here: 227 -> 110 kB, 66 -> 31 kB gzip).
- CSP: `app._app_csp(index)` = `script-src 'self'` + sha256 of index.html's inline scripts (cached on mtime/size),
  on the SPA fallback response. HTML widgets: `/ext/<id>/widget-frame` (bridge `WIDGET_BRIDGE` + widget.html,
  `CSP: sandbox allow-scripts allow-pointer-lock`), theme in the URL fragment; HtmlWidget loads it by `src`
  (an srcdoc frame inherits the parent policy). Page extensions may not inject inline scripts nor use eval.
- security: cookie `<ts>.<nonce>.<hmac>` (legacy `<ts>.<hmac>` accepted); `revoke_cookie()` on POST /api/auth/logout -> secrets.json `revoked_sessions {id: expires_at}` (pruned, max 500, overflow -> `sessions_not_before`); `set_password` clears it; `cookie_valid` reads secrets.json once.
- cmd_core: `HARDENING` drop-in `claude-maxxing.service.d/10-hardening.conf` (install.sh writes the same text), `maxxing harden [--undo] [--no-restart]` (write, daemon-reload, restart, health check, restore on failure), doctor check `hardening` (INFO), uninstall removes the drop-in.
- filesite/rich.tsx: CSP/iframe sandbox without `allow-popups-to-escape-sandbox`.
- new `maxxing/uploads.py`: `UploadGuard` ASGI middleware for multipart under /api/ (401/403 before reading the body, 413 `too_large`, 507 `disk_full`, also while streaming), `check_room()` / `limits()`; config `upload_max_mb` (2048), `upload_min_free_mb` (1024); `save_upload` checks per file and counts bytes.
- feedhooks: `SIGNED_KINDS` (stripe, shopify, github) without a secret -> `401 secret_required` + feed.system warning grouped `hook-secret-<id>`; creation without a secret still allowed.
- telegram: `Gateway.authorized` requires the user in `telegram.user_ids` (empty list = nobody); `_try_link` refuses a message without `from`; doctor WARN when linked without user ids.
- cmd_update: config `update_verify_signature` (false) -> `verify_target()` (`git verify-commit`, else `git verify-tag` on `tag --points-at`) before any change, exit 1 + `_notify`; skipped on licensed installs; doctor check `update_signature`.
- docs/upgrade/2.0.0a32.md: `maxxing harden` (ask first), unsigned webhook sources, Telegram linked without owner, what to tell the user.
- health.services(force): one `systemctl show <units>` (blocks matched by Id), 10 s cache,
  `invalidate_services()` from the service action route; `_systemctl_show_all(names)` (tests patch it instead
  of `_systemctl_show`).
- trash.list_items: listing cache keyed by `_dir_sig` (scandir stat of every entry), per-item size cache,
  `PURGE_EVERY_S` = 3600, expired items hidden; `invalidate_sizes()` (backup._apply calls it).
- api/system.version_info: `_local_info` cache (`LOCAL_TTL` 30 s + `_git_sig`), `invalidate_version()`.
- config.load_config: pickled cache keyed by config.json stat + defaults identity; still returns a copy.
- widgets.Builtin.sig + `CARD_CACHE_S` (10 s): crons/day cached on `_crons_sig()`; `invalidate_cards()`.
- sessions/spawn: `_wait_unit_gone` (`UNIT_POLL_S` 0.05, `UNIT_GONE_WAIT_S` 3), 3 attempts instead of 6.
- sessions/clip: `INIT_KEEP`, `DROP_SUBTYPES`, `keep_event`, `drop_line`; runner skips dropped events;
  `service.compact_log` drops/slims lines too.
- cli.main configures only the chosen sub-command; cmd_cron/cmd_feed/cmd_license/cmd_core/health import their
  heavy modules lazily; `cmd_core._password_set()`.
- search: `checkpoint()`, `WAL_LIMIT`, `CHECKPOINT_BUSY_MS`; refresh checkpoints when `total_changes` moved.
- Tests: conftest `_fresh_caches` autouse fixture resets the new in-process caches.
- Sessions grid: `Col` gets `below?: boolean` (stacked under the previous column; `normalizeCols` keeps it valid:
  never first, never under another `below`, applied on persist merge, close, move). New `rowSplit` (0.2..0.8,
  share of the top pane, persisted in `mx-sessions` v2 - no version bump, missing = 0.5). Actions `stack`,
  `unstack`, `toGrid` (odd indices below), `toColumns`, `setRowSplit`.
- The strip is a CSS grid: every pane stays a direct child (placed with `gridColumn` / `gridRow`, a full pane spans
  both rows), so stacking never remounts a thread. Column widths are on the grid template (`minmax(380px, Wpx)`),
  resized live through `StripContext` then saved; the row handle lives on the bottom pane. Moves animate with a 2D
  FLIP (translate + a short dip of opacity when the height changes); the bottom pane appears with `animateIn('y')`.
- `StackedComposer`: in a stacked pane, the composer collapses (`grid-rows-[0fr]`, `inert`) unless the column is
  focused; the folded "Write..." bar focuses the column and the composer. `EASE_OUT` exported from `lib/presence`.
- `Thread`: the pinning ResizeObserver also observes the scroller (the view shrinking - composer, queue card, grid
  row, window, keyboard - used to leave the last rows under the composer). `pinned` is released only by a scroll
  that moves up (`scrollTop` lower than the previous event) and lands more than `PIN_PX` from the bottom; scrolls
  going down (smooth jump to latest) and layout clamps keep it.
- Strip panes stay in the DOM in the order they were opened (`domCols` in `pages/sessions/index.tsx`): the grid
  places them, and moving a node in the DOM reset its thread's `scrollTop` to 0 (a moved session showed the top
  of its conversation).
- Layouts (`pages/sessions/layouts.ts`): a layout is `Slot[]` (`one` / `big` / `pair`) per strip column;
  `layoutsFor(n)`, `slotsOf(cols)`, `arrange(cols, slots, move?)`. `Col.wide` (no set width: `2fr`, dropped on a
  `below` col); `applyLayout(slots, move?)` clears `widths`. `LayoutPicker.tsx`: Radix popover anchored on the
  grip (`holdOpens`: opens after the button is held still 350 ms - moving 4 px or a dragstart cancels - and stays
  until a choice / Escape / outside click) or on the grid button (300 ms mouse hover, closes 220 ms after leaving);
  `LayoutDropBar`: while `dragging` (store, set one frame after the grip's dragstart, cleared on dragend / drop) a
  pill at the top of the strip unfolds into the layouts on dragenter, zones take the drop (`applyLayout(slots,
  { key, zone })`). `layoutPicker` (store, not persisted) opens the grip's picker from the column menu with the
  focus inside.
- Hidden messages: `POST /api/sessions/{id}/hide {at, hidden}` appends `{type:"mx_hide", ref, hidden}` to the raw
  log (append-only: offsets, streams and backward pages unchanged), normalised as `{type:"hide", ref, hidden, at}`.
  `log.ts` folds them into `LogState.hidden` (by the user event's `at`; older pages merge theirs under the newer
  ones), `withoutHidden` drops a hidden message with its turn (rows up to the next message), `unanswered` = user
  messages whose turn has no assistant / thinking / tool row (the last one only when not running): only those get
  the right-click menu and the bin (`UserMessage.onDelete`). `setHiddenLocal` hides at once; rows slide out
  (220 ms) first; toast with Undo (`hidden: false`). Claude's transcript is not touched; search still indexes the text.
- Layout catalogue (`layouts.ts`): `layoutsFor(n)` only returns layouts that place all `n` sessions (2: side by side,
  main left / right, stacked; 3: three columns, main + stacked both ways, column + stacked; 4: grid, four columns,
  main + column + stacked both ways; 5+: grid, main + grid both ways, columns), `fitting(all, room, MIN_W)` keeps
  those whose strip columns fit the strip width (never none), `layoutName` labels them. `MIN_W` moved to
  `layouts.ts` (re-exported by `Column.tsx`).
- Snappier motion: hold 250 ms / hover 200 ms / leave 150 ms, drop bar 150 ms without backdrop blur or padding
  transition, thumbnails `mx-unfold`, column FLIP 180 ms (running slides are cancelled before measuring, so a quick
  second change starts from the real place), stacked composer 200 ms, deleted message 150 ms.
- Grid speed (measured with CPU x4, production build: grid on 877 -> ~330 ms of long tasks, focus change 222 ->
  ~160 ms, drag start 208 -> ~100 ms, layout drop 429 -> ~300 ms): `ColumnFor` and `LiveThread` are `React.memo`
  (the page re-renders on every focus change, the columns and threads no longer do; `onRetry` / `onLoadEarlier` are
  stable per session); `StackedComposer` hides the box (`hidden`, still mounted) and fades it in with WAAPI instead
  of animating `grid-template-rows` (that re-laid out and repainted the conversation above on every frame); the
  drag image is the column header, not the whole column; in a stacked pane the composer grows to 4 lines
  (`Composer maxRows`).
- Pairs stay pairs (`store.ts`): `detach` gives the session under a closed / moved / re-stacked top its own column
  (it used to slide under the previous column); `moveBeside(key, target, side)` (drops) and `shift(key, dir)` +
  `canShift` (column menu) move by strip column, a session of a pair leaving it on that side; `move` never lands
  between a pair. `becomeSession` keeps `wide`; `stack` drops it. The width handle shows only with two strip columns
  or more (`StripContext.columns`).
- Hidden messages: `hideMessage()` is a plain call (each hide / undo keeps its own outcome: a fast error no longer
  re-hides after the slide-out, a failed undo hides again with a toast); while a session runs, nothing after its
  last finished turn can be deleted (a steered message included). The drop bar is not shown when the drag ended
  before its first frame.
- `POST /hide`: 404 when no user message has that `at` (the log is scanned for `mx_user` / `mx_hide` lines), no line
  written when the message is already in the requested state (the log cannot be grown by repeated calls).

## 2.0.0-alpha.31 - 2026-10-16

- `useMut` (`lib/queries/util.ts`): the hook's own `onSuccess` (usually writing the server's answer into the cache)
  now runs BEFORE the invalidations are awaited - a toggle no longer waits for the refetch of every invalidated
  query (sessions list + workspace tree for a session PATCH). New option `optimistic: (vars) => [{ key, update }]`:
  patches every cached query under each key prefix in `onMutate`, restores them on error (before the toast).
- Optimistic: `usePatchSession` (title, model, archived, notify, plan_mode, favorite - not `path`),
  `useMarkFeedRead`, `useSaveFeedSettings`, `useToggleExtension`, `usePinExtension`, `usePutSecret` (note /
  expose; a new value still waits), `useTelegramSettings`, `useClaudeSettings`, `useVoiceSettings`. Already
  optimistic: settings, crons toggle, tasks.
- `health.usage`: token from `claude_oauth_token` (vault) first, else `claude_auth.credentials_file()` (was only
  `~/.claude/.credentials.json`, so `setup-token` servers always got `no_oauth_credentials`); `api_key` reason when
  only an API key is stored. 429 -> `_usage.blocked_until` = now + Retry-After (30 s..2 h, default 15 min): no call
  until then, even with `force`, last good values returned `stale: "rate_limited"` + `retry_at`. Widget and
  Settings -> Statistics turn the reason into a sentence.
- Logo files: `web/scripts/gen-icons.py` draws the logo once as SVG (512 grid: rounded square r=112, body path,
  eyes, collar, buckle, leash; body gradient = the blue stops hue-rotated per accent) and renders with Chromium:
  `logo-<a>.svg` (used by `logoSrc`, favicon, splash, offline page), `logo-<a>-64|128.png`, `icon-<a>-192|512.png`
  (rounded, transparent corners), `icon-maskable-<a>-512.png` (full bleed, 78 % safe zone),
  `apple-touch-icon-<a>.png` (full bleed, opaque), `manifest-<a>.webmanifest`, and the blue defaults under the old
  names. `index.html` (before the first paint) and `accent.applyFavicon` point the icon / `manifest` /
  `apple-touch-icon` links at the accent's files; the splash `<img>` has no `src` in the markup (it fetched the blue
  logo first). Notifications use `appIconSrc(accent)`; `offline.html` reads the accent from `mx-ui` (primary color +
  the accent SVG, the blue SVG embedded as fallback).
- Mobile: `globals.css` `@media (pointer: coarse)` forces 16 px `!important` on inputs (not checkbox / radio /
  range / file / color), textareas, selects and `[contenteditable]` - utilities like `text-[13px]` (sessions tree
  filter), `text-xs` (viewer filters) and CodeMirror's 12.5 px used to bring back iOS's focus zoom.
  `html { touch-action: manipulation }`; viewport `interactive-widget=resizes-content`.
- Hit areas (`before:-inset-2.5`) on the composer attachment "×", task label "×", backup pattern "×" and the task
  column selector.
- Audit: every route + its menus / popovers / dialogs / sheets (palette, task sheet, cron editor, rename / emoji,
  column menu, model picker, install dialog, file viewer, code editor) at 360x800, 375x667, 393x852, 768x1024
  (touch emulation): page overflow, elements off screen, fields < 16 px, overlays out of the viewport. Before: 5
  fields < 16 px; after: 0 issues in 427 states.
- Page data, web: `pages/pageData.ts` (`prefetchPageData(qc, pathname, search)`, `prefetchShell`, `prefetchPage`,
  `usePrefetchLink`) maps a URL to its page's queries (dashboard + feed, sessions (moved from `lib/boot.ts`),
  files kind probe, tasks, crons + runs(8), feed pages, settings sections, docs, extensions). Called by
  `bootPrefetch`, by a `loader` on the AppShell route (`createAppRouter(qc)`; `shouldRevalidate` = pathname
  change or new `/files` search) and by the sidebar / tab bar `NavLink`s (`onPointerEnter` / `onFocus` /
  `onTouchStart`: chunk + data). New query option factories next to their hooks: `dashboardQuery`, `feedQuery`,
  `feedPagesQuery`, `tasksQuery`, `cronsQuery`, `cronRunsQuery`, `docsQuery`, `docQuery`, `fileListQuery`,
  `fileKindQuery(qc, path)`, `servicesQuery`, `tokenStatsQuery`, `secretsQuery`, `backupQuery`, `trashQuery`.
  `pages/prefetch.ts`: `PAGE_LOADERS` is keyed by first path segment (+ feed, docs, x) and
  `prefetchPageChunk(pathname)`. The files kind probe fetches the parent listing alongside the root's.
- Motion: `.mx-card-in` 320 ms, `20ms + i * 32ms` (was 420 ms, `60ms + i * 55ms`), dashboard `--i` capped at 6
  (was 12); `SectionStack` `--i = min(i, 4)` (was `min(2 + 2i, 10)`); boot entrance shorter (`#main` 300 ms
  + 40 ms, items 320 ms from 60 ms + 30 ms * i); the session tree intro plays once per tab (`introPlayed`).
- Settings: `lib/fonts.loadFontPreview(stack)` (idle queue, one font per idle callback, starts after 250 ms) for
  the font picker; `Combobox` `options` may be a function (built on open) + `labelOf(value)` for the closed
  trigger; `timezoneOptions` passed as a function (`timezoneLabel`). Navigation to Settings, 4x CPU: main-thread
  script ~980 -> ~440 ms.
- Queries: `refetchOnWindowFocus: (q) => !isLiveKey(q.queryKey)`; `LIVE_KEYS` = sessions, workspace, tasks, crons,
  trash, extensions, health, telegram, backup. `useGlobalBus` invalidates `LIVE_KEYS` on `visibilitychange` back
  to visible after >= 60 s hidden. `useFeed` polls every 5 min (was 1 min). Feed page: sources and unread from
  its first infinite page (kept while a filter loads), no `useFeed(null, false, 1)` request.
- Sessions: `index.tsx` and `Tree.tsx` read `useSessionsUI` through selectors / `useShallow`. `log.ts`:
  `useSessionStream(id)` (load + SSE, re-renders on ready/deleted only), `useLogSelect(id, select)`;
  `useSessionLog(id, live)` = subscription + `useSessionStream(live ? id : null)`. `SessionColumn` opens the
  stream and reads `deleted`; `LiveThread` subscribes to the log. `useSetSessionCache`: list writes whose only
  differences are `updated, cost_usd, context_tokens, context_window, real_model, last_text` are throttled to
  one per 2 s per session; the `one` query is always written.
- Dashboard: `SOFT_S = 1.5`: `GET /api/dashboard` lists a widget still computing as `pending: true` (card null,
  error null); `_inflight` shares one computation per widget between requests (`GET /widgets/{id}` joins it, a
  forced one starts afresh). Web: `useFillPendingWidgets` fetches pending widgets one by one and patches them in;
  `WidgetCard` memoised; pending cards show a skeleton. HTML widget card `updated` = widget.html mtime (now when
  forced) - the frame is keyed on it.
- crons: `_all_runs()` caches the parsed runs.jsonl on (path, mtime_ns, size); `read_runs` returns copies.
- Files: `Listing` renders `RENDER_STEP` (200) entries, +200 when a sentinel comes within 800 px of the scroller
  (IntersectionObserver), always up to the selected entry + 50. Thumbnails run in `_thumb_pool`
  (`ThreadPoolExecutor(THUMB_JOBS=3)`) instead of the default executor. `_list` uses `os.scandir` (`_scan_entry`,
  same fields): 1 500 entries 23 -> 14 ms.
- Docs: `all_docs()` cached on the folder signature (names, mtime_ns, sizes); `GET /api/docs?full=1` adds
  `markdown`; `useAllDocs(enabled)` = one query (`qk.docs.full`) that seeds `qk.docs.page(slug)`.
- Extensions: `page_v` (page.js mtime in ms) in the extension info; the page host imports
  `page.js?v=<page_v>` (`-<attempt>` on retry) and waits for the extensions list (a shell query).
- Build: `Combobox` and `QRCode` are no longer re-exported by `components/ui/index.ts` (import
  `@/components/ui/combobox` / `qr-code`); `cmdk` left the `vendor-ui` group. Startup chunks 734 -> 710 KB raw.
- Measured (bench copy of a real state, 4x CPU, median of 3; script kept outside the repo): cold loads, content
  visible: 1 500-file folder 4.5 -> 1.7 s, Settings -> General 1.8 -> 1.2 s, Files 1.3 -> 1.0 s; navigation to
  Settings 1.0 -> 0.55 s; dashboard complete after navigation ~1.2 -> ~0.9-1.0 s. Other pages within noise.
- Not done: virtualising long lists (progressive rendering instead), one shared EventSource per session (HUD +
  column still open one each), lazy settings sections, longer stats / Claude models caches (1 ms / 8 ms here),
  caching `crontab -l` (2 ms), the archived sessions list fetched with the tree (it feeds the per-topic
  "Archived (n)" counts and the search).

## 2.0.0-alpha.30 - 2026-10-15

- PWA install: `useInstallMode()` -> `'prompt' | 'guide' | null` (null only when running installed or after
  `appinstalled`); `installApp()` uses the deferred `beforeinstallprompt`, else opens the guide dialog
  (`usePWA.helpOpen`, replaces `iosHelpOpen`). `pwa/InstallSteps.tsx`: `detectPlatform()` (chrome, edge, safari,
  firefox, ios, android), `InstallSteps`, `InstallGuide` (platform switch + https warning when
  `!isSecureContext`). Settings -> General: `AppCard` (install button, steps, QR code of `location.origin`,
  iPhone and Android steps); the install row left the Help card. i18n `pwa.ios.*` replaced by `pwa.steps.*`,
  `pwa.p.*`, `pwa.card.*`, `pwa.guide.title`, `pwa.needsHttps`, `pwa.browser`.
- Perf, web: entry CSS only has Inter (`globals.css`); the 29 other `@fontsource-variable` packages are dynamic
  imports in `lib/fonts.ts` (`loadFont(stack)`, called by `applyFonts` and by each Settings font button). The
  service worker precaches only `inter-latin-wght-normal` (was every family's `latin-wght-normal`, ~1 MB); other
  font files are cached on first use by the `/assets/` cache-first rule. A non-default font shows its fallback
  until its CSS chunk arrives (font-display: swap).
- Perf, web: `i18n/fr.ts` is a lazy chunk (`loadLanguage(lang)`, `useT` re-renders on arrival via
  `useSyncExternalStore`); `main.tsx` awaits the active language before `createRoot` and loads the new one on
  every language change. `en` stays static (fallback, `TKey` source).
- Perf, web: highlight.js grammars moved to `components/ui/highlight.ts` (lazy). Code blocks render plain until
  the first one with a language triggers the import, then every mounted `Markdown` re-renders highlighted
  (same output as before).
- Perf, web: `BUS_KEYS.sessions` = `['sessions']` only; `BUS_TURN_KEYS` (claude status, token stats) are
  invalidated when a batch has both `sessions` and `workspace` (the watcher pairs them on state/unread changes).
  `useEventSource` `onReconnect(downMs)`; the global bus refreshes the bus-covered keys only after >= 5 s down
  (was: every active query on every reconnect).
- Perf, server: `api/sessions._sse` ticks with one `to_thread` stat of log + meta (`service.meta_ident`); events
  are read only when the log grew, the Session only when the meta changed (or every 1 s while running, so a dead
  runner is still repaired by `_effective`). Same frames and order. `store.read_cached` (+ `forget_cached`) used
  by `list_sessions` / `get_session` (300 metas: 26 -> 12 ms per list).
- Perf, server: hot JSON endpoints (`/api/sessions`, `/api/workspace/tree`, session events, `/api/files/list`)
  return a `JSONResponse` of plain data (no `jsonable_encoder`): 300 sessions 37 -> 18 ms, tree 24 -> 18 ms,
  1500 files 53 -> 38 ms. `store.sessions_dir()` creates the folder once per state dir.
- Perf, server: `JsonGzip` (pure ASGI) gzips `application/json` responses >= 1 kB (level 5) when the client accepts
  gzip and there is no `X-Forwarded-For` (direct Tailscale / local access; Caddy's `encode` does it in domain
  mode). SSE and files untouched. Added before `_SecurityHeaders`, which stays outermost.
- Perf, web: `lib/format` caches Intl formatters per language + options; when the highlight chunk arrives only the
  `Markdown` blocks with a fenced code block with a language re-render.
- Perf, web: `index.html` preloads (low priority) the chunk of the URL being opened with its imports and the UI
  language's dictionary (route table read from `src/routes.tsx` at build time). `lib/boot.ts`: once the early
  auth check says signed in, the shell's queries and, on `/sessions`, lists, statuses and the open sessions'
  thread tail are fetched with the hooks' own keys (the early tail is used once, within 15 s; the stream resumes
  from its offset).
- Perf, web: a freshly opened thread renders its last 30 rows first, then prepends the rest of its first page
  (120 rows) in 30-row slices on idle callbacks with the "show earlier" anchoring; if 30 rows do not overflow the
  view by 600 px the whole page renders before the first paint. Cold `/sessions`, 300-row session, 4x CPU:
  3.8 -> 3.0 s (with the boot prefetch), warm 2.9 -> 2.3 s.
- Not done: `content-visibility` on thread rows (the thread does its own anchoring with `overflow-anchor: none`;
  placeholder heights would make the view jump while scrolling up). `cmdk` stays in `vendor-ui` (combobox.tsx in
  the eager `ui` barrel uses it: moving it only shifts bytes into the `ui` chunk).
- `pages/sessions/store.ts`: new `listBy` `project|session`; `treeMode` is now `tree|drill` only; `flatSort` gains
  `used` (default): `(turns + 1) * 0.5 ** (days since updated / 7)` (`Tree.tsx` `usage()`). Persist version 2:
  `migrate` turns a v1 `treeMode: 'flat'` into `listBy: 'session'` and sets `flatSort: 'used'`.
- `Tree.tsx`: header = `ListBySwitch` (one icon button) + search icon (the filter `Input` mounts on demand,
  `data-testid` `tree-search` / `tree-filter`); `SessionRow` `compact` (one line, topic only, `project › topic`
  in `title`) used by the session list and the Favorites / Recent blocks; empty Favorites block not rendered
  (`sessions.fav.empty` removed). `topicLabel(path, root, sep)` takes the separator (labels use ` › `).
- `ColumnShell`: the saved width is ignored while `count === 1` (no resize handle either).
- Diagrams: `components/ui/diagram.tsx`, used by `Markdown` for ```` ```mermaid ```` blocks. New dependency
  `mermaid` (^11), dynamically imported on the first diagram (its chunks are not in the SW precache);
  `securityLevel: 'strict'`, theme `dark` / `neutral` from the `dark` class (MutationObserver), renders
  serialized through one queue, debounced 250 ms; parse errors keep the last good SVG (or show the code).
- `templates/workspace/CLAUDE.md`: section "Answers shown in the UI" (absolute paths inside files_root, small
  mermaid diagrams); `docs/upgrade/2.0.0a30.md` adds it to existing workspaces.
- Wording: the assistant persona is "Harness" in user-visible strings (`web/src/i18n/en.ts` + `fr.ts` values only,
  no key renamed - `crons.kind.claude*`, `files.askClaude`, `system.askClaude` keep their names). "Claude" kept for the
  account/CLI/auth/subscription (`claude.*`, `settings.claude`, `onb.claude.*`, `system.claudeAuth`, usage/quota,
  `import.desc` sources). Server: Telegram gateway texts (status "Harness travaille…", queue/close replies, /help, link
  confirmation, feed button "🤖 Ask Harness"), runner/normalize session notes, cron failure fallback text, Shopify
  connect card. Log/doctor/CLI strings unchanged. Docs: only lines quoting a renamed label.

## 2.0.0-alpha.29 - 2026-10-15

- Login throttle (`security.begin_attempt` / `end_attempt`, `throttle()` kept as a wrapper): the refusal is decided
  before scrypt (a blocked client gets `429` even with the right password); each attempt is recorded as a failure
  up front (parallel requests count), a success clears the client. Global cap `GLOBAL_FAIL_MAX` = 30 failures in
  the window -> one password check per `GLOBAL_GAP_S` = 5 s for everyone (others `429`, message "try again in a
  few seconds"). `_fails` pruned on every attempt (entries > `KEEP_S` = 1 h, empty keys). Alerts / feed use
  `client_key` (uvicorn trusts proxy headers from 127.0.0.1 only) instead of the raw `X-Forwarded-For`.
- `filesite`: token payload may carry `f` (single file) - set when the page's folder is files_root, `$HOME`, `/`
  or has a dot component; any rel path with a dot component -> 403 (also checked on the resolved path relative to
  the folder); `dir/` -> `index.html` resolved again and re-confined. `read_token` returns `(folder, file|None)`.
- `files._file_headers`: sandbox CSP on every `/raw`, `/preview`, `/thumb` response except image/* (not SVG),
  audio/*, video/*, application/pdf (Chrome's PDF viewer refuses `sandbox`). `_ACTIVE_TYPES` removed.
  ffmpeg inputs (`_ffmpeg_thumb`, `voice.normalise`) get `-protocol_whitelist file`.
- `api/hooks.py`: `feedhooks.by_token` first (404 without reading), Content-Length > `MAX_BODY` -> 413, then the
  stream is read with the same cap. HMAC checks unchanged (`feedhooks.deliver`).
- Extensions: `forward` refuses `.` / `..` path segments (`400 bad_path`); `HtmlWidget` encodes each segment of
  the frame's path and refuses dot segments (also percent-encoded) - the browser would have normalised
  `../../x` out of `/api/ext/<id>/` before any server check.
- `app._SecurityHeaders` (pure ASGI): `nosniff`, `X-Frame-Options: SAMEORIGIN` (same-origin PDF / page iframes),
  `Referrer-Policy: same-origin`, and for non-API `text/html` `frame-ancestors 'self'; object-src 'none';
  base-uri 'self'` (index.html has inline scripts: no script-src). Headers set by a route are never overridden.
- `vault.RESERVED` (+ `spawn._RESERVED` fallback): LD_AUDIT, BASH_ENV, ENV, PROMPT_COMMAND, NODE_OPTIONS,
  NODE_PATH, PYTHONSTARTUP, PYTHONHOME, GIT_SSH_COMMAND, GIT_EXEC_PATH, ANTHROPIC_BASE_URL. Existing entries with
  these names stay in the vault but `exposed_env()` drops them. `ANTHROPIC_API_KEY` deliberately not reserved
  (legit for user scripts; the stored Claude credential still wins in `auth_env`).
- `importer._claude_config`: `.mcp.json` and anything under `.claude/` except `skills/` and `*.md` -> skipped
  (listed with a reason). Tests: `tests/test_security.py`.
- Quote (web only, no API change): `pages/sessions/Quote.tsx` (`QuotePill`, portal, scoped to the column body;
  selection must sit inside one `.mx-assistant` - thread replies and the side-question answer; shown on mouse
  pointerup or after `selectionchange` settles on touch / keyboard). `ComposerHandle.quote(text)`; composer quotes card
  between the notice and the composer; quotes persisted in localStorage `mx-draft:<key>:quotes` (JSON array,
  `loadQuotes` / `saveQuotes` in `store.ts`, cleared with the draft on delete). Sent text = `quotesMarkdown()`
  blockquotes + blank line + typed text; `UserMessage` renders the leading blockquotes via `splitQuotes()` (Copy
  keeps the raw text). Utils in `util.ts`.
- Unread badge: `CountBadge` / `CountDot` tone `unread` and the new `StatusDot` tone `unread` use `--success` (see-through +
  inset ring) instead of sky-500; `mx-badge-pulse` pulses in `--success` (color-mix). Running stays `--primary`.
- Badge clicks (sidebar counters and dot, tab bar, tree project/topic `Badges`) filter the tree: `features/notify/showSessions.ts` -> `/sessions?show=running|unread`
  (URL intent) -> `useSessionsUI.show` (not persisted; un-hides the tree). `Tree.tsx` then lists only those sessions
  (`forceOpen`, archived hidden, animations off) with a chip (count, **Open all** = `onOpenSession` for up to 6, ×);
  typing a search clears it.
- Column resize handle: `left-full -ml-px w-2` (outside the column, never over its scrollbar; a 3 px `after:` line lights
  up); the column strip has `pr-2` so the last column's handle fits without making the strip scroll.

## 2.0.0-alpha.28 - 2026-10-15

- Feed: `maxxing/feed.py` (sqlite `<state>/feed.db`, dedupe per source, `group` folding of unread rows within 24 h,
  30-day retention), `feedhooks.py` (stripe / shopify / github / generic parsers + signatures, 1 MB, 120/min/hook),
  routers `api/feed.py` (+ 3 s watcher -> bus "feed") and public `api/hooks.py`. Config `feed {telegram, rules,
  hooks}`, secrets `feed_hooks`. System events: cron runs (`crons._feed`), update available / needs attention,
  sign-ins (folded). CLI `cmd_feed.py`. Skill `maxxing-feed`. Docs `docs/user/24-feed.md`.
- Telegram: special thread `#feed` "Notifications" (created when `feed.telegram`), `feed_notify` with inline buttons
  (Ask Claude `f:<id>`, Open), `_post`/`send_key`/`_send_sync` take `markup`. **Fix**: `_migrate_topic_threads` and
  `_path_for` only knew Crons/Alerts and would have deleted (and recreated) any other notification thread on every
  sync -> `NOTIFY_ONLY`.
- UI: `features/feed/FeedItems.tsx` (item, panel), `pages/feed` (route `/feed`), `features/feed/FeedSettings.tsx` in
  Settings -> Notifications, dashboard grid 2 columns up to 2xl when the panel is open (`ui.feedPanel`), bus topic
  `feed`.

## 2.0.0-alpha.27 - 2026-10-15

- Docs pass: 01-welcome feature list, README features + doc links, INTERNALS (project emoji, `move_session`,
  `favorite`, Telegram thread names), `templates/workspace/projects/system/topics/help/CLAUDE.md` page table
  (20-23 added, summaries refreshed). Templates are only copied when missing -> the upgrade note refreshes the
  table in existing workspaces.

## 2.0.0-alpha.26 - 2026-10-15

- `service.move_session(sid, path)` (PATCH `{path}`): validates the topic, refuses while running / queued (`409 busy`),
  rewrites `meta.path` and moves `~/.claude/projects/<slug of cwd>/<csid>.jsonl` (`_move_transcript`, shared with
  `remap_paths`) so the next `--resume` finds it. UI: `MoveSessionPicker` in the column header (Combobox with a custom
  `trigger`, new prop) + expands the destination in the tree.

## 2.0.0-alpha.25 - 2026-10-15

- `topic_name()` / `topic_label()` / web `labelOf`: the emoji is a prefix of `<project>/<topic>` (it no longer replaces
  the project name). Existing threads are renamed once more at the next sync.

## 2.0.0-alpha.24 - 2026-10-15

- Project emoji: `workspace.project_emoji / set_project_emoji / check_emoji` (one emoji: <= 8 code points, no
  ASCII letters / digits / spaces), stored in `projects/<p>/.maxxing.json` (moves with renames and the trash, added to
  `backup.ALWAYS`); `Project.emoji` in the tree; `PATCH /api/workspace/projects/{p} {emoji}`.
- Telegram: `topic_name()` always includes the project - `"<emoji> <topic>"` or `"<project>/<topic>"` (the `topics`
  argument is now unused) - so `session_label` = `"🛒 blog · Title"`; `topic_label()` (where / "Where?" buttons) uses the
  emoji too. Workspace events also schedule a thread sync. Tests updated to the new names.
- UI: `EmojiDialog` (40 picks + free input) from the project menu (tree and drill-down); emoji before the project name
  (tree, drill rows / headers) and in session labels (`labelOf` built once in `SessionTree`).

## 2.0.0-alpha.23 - 2026-10-15

- `DropdownMenuCheckboxItem` always draws its box (bordered, filled with the accent when checked; `group/cb` on
  `data-state`). Sessions list: reverse-order button removed; `flatDesc` is forced to the natural order of the
  sort (`merge`: newest first, A to Z for names).

## 2.0.0-alpha.22 - 2026-10-15

- Session meta `favorite` (PATCH `{favorite}`, in every `Session`, copied to the continuation by `handoff`).
- `pages/sessions/store.ts` (persisted `mx-sessions`, validated in `merge`): `treeMode` `tree|drill|flat`, `drill
  {project, topic}`, `flatSort` `recent|name|created` + `flatDesc`, `showFavorites` (default on), `showRecent` (off),
  `recentCount` (3/5/10/20, default 5). `Tree.tsx`: `TopBlocks`, `DrillView` / `DrillHeader` / `DrillRow`, `FlatView`
  (pages of 60), footer `ModeButton` + quick action + `ListOptions`; project / topic menus shared
  (`ProjectMenuItems`, `TopicMenuItems`); `SessionRow` takes a `label` (project / topic) and has the favorite toggle.
  A search shows the filtered tree in drill mode and a filtered flat list in flat mode.

## 2.0.0-alpha.21 - 2026-10-15

- Viewer and `FilePreview`: "Open in Files" is a link, `target=_blank` on desktop (viewer not closed), in-app navigate on
  mobile.

## 2.0.0-alpha.20 - 2026-10-15

- Viewer: **Edit** (textual kinds, not when `/read` says `editable: false`) -> `/files?path=…&edit=1`, `target=_blank` on
  desktop, in-app navigate on mobile (PWA). `FileView` starts rendered kinds in `edit` mode when `edit=1`.

## 2.0.0-alpha.19 - 2026-10-15

- Viewer: `viewerStore` normalises paths (trailing slashes stripped) in `show` / `setList` - `useFileKind('/a/b/')`
  looked up an empty name in `/a/b`, returned `missing`, and the disabled content query stayed `isPending`
  (skeleton forever). The pane now renders an EmptyState for `missing` and probe errors (403 = outside the files root).
## 2.0.0-alpha.18 - 2026-10-14

- File viewer (`features/files/Viewer.tsx`, state `viewerStore.ts`, host lazy-loaded by `AppShell` on first open):
  Radix dialog, side panel (`min(860px, 94vw)`) or fullscreen (`mx-viewer-full` in localStorage, always on mobile),
  ← / → in a capture-phase keydown listener (before page hotkeys; ignored in fields, CodeMirror, media player),
  touch swipe, `useFileKind` probe -> folder grid (`FolderView`) or `PreviewBody`, neighbours prefetched.
  Sessions: `PreviewProvider` no longer renders a Sheet; it calls `openFileViewer(path, threadFiles(thread))`, the
  list = every `[data-mx-file]` button and `a[href^="#mx-file="]` link of the clicked thread (`[data-thread]`).
  Files page: prev / next over every file of the folder (was images only, `files.unsavedNav` when dirty) + a
  fullscreen button opening the viewer on the folder's files.
- New kinds in `kinds.ts`: `csv`, `html`, `font`, `other` (known binaries, info card); `archive` = listable
  (zip/tar/gz); `isRendered()` = markdown|csv|html (Preview/Edit/Split on the Files page); TIFF/HEIC are images
  (`CONVERTED_IMAGE`: the viewer never loads the original). Views in `features/files/rich.tsx`: `CsvView`
  (RFC 4180 parser, delimiter guess, sort, filter, 500-row pages), `HtmlView`, `ArchiveView`, `FontView`
  (FontFace API), `FolderView`.
- Server: `/api/files/archive` (zipfile / tarfile, no extraction, 5000 entries), PDF thumbnails (`pdftoppm` ->
  ffmpeg WebP, cache key `|pdf`), `/preview` always converts TIFF/HEIC. HTML pages: `/api/files/site-url` +
  router `api/filesite.py` (`/api/files/site/<token>/<rel>`, token = base64 `{d: folder, e: exp}` + HMAC with
  the cookie key, 2 h; no cookie auth since a sandboxed opaque-origin frame does not send the strict cookie).
- install.sh: Caddy `X-Frame-Options` DENY -> SAMEORIGIN (DENY blocked our own PDF and page previews in domain
  mode); `docs/upgrade/2.0.0a18.md` fixes existing Caddy sites.

## 2.0.0-alpha.17 - 2026-10-14

- UI prefs: `tint: 'neutral' | 'tinted'` in `mx-ui` (validated in `merge`), `data-tint` on `<html>` (store +
  index.html inline script). Each `[data-accent]` rule sets `--accent-h`; `[data-tint='tinted']` and
  `.dark[data-tint='tinted']` override the neutral tokens with low-chroma oklch values on that hue.
- Fonts: `lib/fonts.ts` = 23 interface fonts with a `group` (`FONT_GROUPS`) and 11 code fonts, all
  `@fontsource-variable` packages (imported in globals.css, ~3.2 MB of woff2 in dist, fetched only when used);
  the stacks are mirrored in index.html.
- tests: race fixed in `test_telegram::test_commands` (/close archives before deleting the thread).

## 2.0.0-alpha.15 - unreleased

- Side questions: `POST /sessions/{id}/ask {question}` -> `{answer, cost_usd, duration_ms}` (`sessions/aside.py`). Runs in the
  server process: `claude -p --output-format json --permission-mode plan --resume <csid> --fork-session
  --no-session-persistence` (whole context, nothing written: thread, queue, meta and log untouched) with
  `ASK_PREFACE`; 409 `no_thread` before the first answer / `busy` (one per session), 429 above 2 running, 504 after
  240 s. UI: **Question** in the waiting-messages card takes the queue back (`/queue/take`) and asks it;
  `pages/sessions/Aside.tsx` (panel above the composer, ×). Not counted in the session cost / stats.

## 2.0.0-alpha.10 - unreleased

- Plan mode: session meta `plan_mode` / `plan_ready` (create, PATCH, `POST /sessions/{id}/plan/approve`). A turn of a
  plan-mode session runs `claude -p --permission-mode plan` (the CLI refuses edits and non read-only commands;
  headless, `ExitPlanMode` is disabled, so the validation is ours) with `runner.PLAN_PREFACE` (the whole plan in the
  final answer). OK turn -> `plan_ready`. Approve = plan mode off + a user item `plan_approved` (kept by steer) whose
  prompt gets `PLAN_APPROVED_PREFACE`; the thread shows the client's localized text. Compact / hand-off turns are
  never run in plan mode. UI: `pages/sessions/Plan.tsx` (PlanNotice in the composer's new `notice` slot, PlanChip), header toggle,
  new-session checkbox, HUD button.
- HUD: `pages/sessions/Hud.tsx`. Chrome/Edge: `documentPictureInPicture.requestWindow`,
  the app stylesheets are copied (absolute hrefs) and the `<html>` theme attributes mirrored by a
  MutationObserver; a React root is created in the PiP document with the app's QueryClient (same JS realm:
  session log cache, SSE and pending store are shared). One PiP window per tab. Fallback: popup on the
  route `/sessions/hud/:id`. Screen share = `getDisplayMedia` (2 fps), the current frame is drawn to a
  canvas (≤ 1600 px, WebP 0.85) and uploaded with `/api/uploads` before each send. Pref `hud` in the
  `mx-ui` store (per browser), toggled in Settings → General.
- HUD view: while running = the prompt being worked on + last 3 steps; idle = the answer since the last prompt
  (markdown, `mediaPaths` shown one at a time with ‹ ›, links/files open in the main window through `go(path)`).
  `POST /messages` takes `hud: true` -> queue item `hud` (kept by steer) -> `runner.HUD_PREFACE` before the
  prompt (short answer; annotate a copy of the capture, `-annotated` suffix, path in the answer). The log keeps
  the user's text only.
- HUD speed: `runner.stdin_payload` sends HUD messages with their images inline (`--input-format stream-json`,
  one user message = text + base64 image blocks; works with `--resume`). Only real PNG/GIF/WebP/JPEG (type sniffed
  from the bytes, never the extension), inside the workspace (the permission mode applies to anything else),
  ≤ 3.5 MB and ≤ 8000 px a side, 4 max - anything else stays a path for `Read`. Steer keeps `hud` only when every
  merged message has it. Claude sees the capture in its first step instead of a `Read` round trip (~2.5 s measured). Paths stay in the
  text. Other messages keep the plain-text stdin. The HUD treats the turn as over on its `result` event (no
  wait for the session refetch) and as running as soon as a message is sent (pending store).
- Settings motion: `SectionStack` (pages/settings/sections/ui.tsx) staggers its cards with `.mx-rise`; the sub-nav
  highlight slides (one element, `transform`).
- Motion: `web/src/lib/presence.ts` (`usePresence`, `animateIn`, `animateOut`, `useFlip`, Web Animations, no
  dependency) on the session tree rows (`SessionRows` in `Tree.tsx`) and the column strip (`Workspace`).

- Files: `GET /api/files/preview` (WebP <= 2048 px for images > 300 KB, cached in `<state>/thumbs`), `v` (mtime)
  on `/raw`, `/thumb`, `/preview` for immutable browser caching. Media paths in messages read by `/events` and
  `/stream` are warmed in the background (`maxxing/media.py` `warm_events`: thumbnails 160/320, preview, video
  poster; 2 workers, each path once). (Fast-start remuxing of late-`moov` videos was measured: no gain in
  Chrome, not kept.)
- Viewer: progressive images (cached 320 px thumb blurred -> preview; the original loads quietly afterwards for an
  instant zoom), prefetch on hover in conversations (`prefetchImage`), own video/audio player
  `features/files/MediaPlayer.tsx`.

## 2.0.0-alpha.8 - unreleased

- Search: `maxxing/search.py`, SQLite FTS5 in `<state>/search.db` (items + external-content fts + triggers,
  `src` signatures: log offset + inode/crc of the head, file mtime:size, tasks.json sig). Background
  refresh every 30 s (api/search.py startup task, `optimize` hourly) + sessions before each query.
  `/api/sessions/search` now goes through it (`service.search`). Palette = the only search UI.
- Steer: `POST /sessions/{id}/steer` merges queued user items into one `steer: true` item at the head and
  sends SIGUSR1 to the runner (`runner_caps: ["steer"]`, else SIGTERM). `Runner.on_steer` ignores a
  steered turn; `STEER_PREFACE` is prepended by `build_prompt`. `POST /sessions/{id}/queue/take` (Edit).
- `Session.queue` no longer counts the head item while the runner has not popped it (state running, no pid).

## 2.0.0-alpha.6 - unreleased

- `POST /api/tasks/bulk` `{ids, patch?, labels_add?, labels_remove?, delete?}`: one atomic write;
  tasks entering a column keep their relative order (top of `done`, bottom elsewhere).
- Session meta gains `tokens {input, output, cache_read, cache_write}` and `days {date: {tokens, cost}}`
  (90 days), updated by the runner (`store.add_usage`). Sessions older than this version are backfilled
  from their log by `stats.py` on the first `GET /api/stats/tokens` (never while running).
- `GET /api/memory`, `POST /api/memory/compact`, setting `memory_max_lines` (default 200, 0 = none),
  `maxxing memory [--json]`; the memory-compaction skill reads the limit with it.
- `GET /api/system/changelog` parses `CHANGELOG.md` (`changelog.py`; `2.0.0-alpha.6` == `2.0.0a6`).
- Session `context_window` (meta + API): from `modelUsage[..].contextWindow` of each result (runner);
  older sessions filled once from the last result of their log (`service._context_window`).
  `<state>/context_windows.json` remembers the window of every model seen (`store.record_windows`), exposed
  as `models[].context_window` in `/api/claude/status`. Gauge order: model chosen for the next turn (if it
  differs) > window of the last turn > window known for that model > 200k, or 1M past 200k.
- Browser preferences (local, `mx-ui`): `notifyDone`, `notifySound`, `badgePulse`.
