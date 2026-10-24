# Technical changes (maintainers)

Private, technical counterpart of `CHANGELOG.md`. `CHANGELOG.md` is **public**: written for users
(what changes for them, plain language), shown in the app ("What's new" after an update) and by
`maxxing update`. This file is for us: API, data formats, migrations, internals, gotchas. It is never
shown in the product. Newest first, same version headings as `CHANGELOG.md`.


## 2.0.0-alpha.98 - 2026-10-24

Radar fixes (FEU).

### bug
- rdf722cd7 `license.remove_key()` replaces the `license` section (`save_config` under `config._lock`) instead of `update_config`, which deep-merged and kept email/kind/status/max_servers/updates_until/activation_id. Test: `test_license.py::test_remove_key_forgets_the_license_info`.
- r8710d993 `feedback.send()` refuses an email over `MAX_EMAIL` = 254 characters (`invalid_email`, 400), like `register.save`; a 1 MB address was sent to the cloud and written to `config.json` (`feedback_email`). Test: `test_feedback.py::test_feedback_email_is_capped`.
- rb6871725 `feedback.send()` and `license._post()` also catch `http.client.HTTPException` (IncompleteRead, RemoteDisconnected...) -> `unreachable` 502 / `LicenseError("network")`. Test: `test_feedback.py::test_a_cut_answer_is_unreachable_not_a_500`.
- rdea19bdd `register.save`, `sync` and `heartbeat` run one at a time (`_serialized`, module `threading.RLock`): two saves at once both POSTed `/v1/register` without a token (two rows, the first token lost). Test: `test_register.py::test_concurrent_saves_make_one_row`.
- rb81922ab `health.issue_id()` keeps the digits inside double quotes (names) and drops the others (ages, counts, exit codes). A mark on such an issue made before this version is lost once. Test: `test_system.py::test_health_issue_marked_seen`.
- rde63e81a `health.mark_seen()` and the write of `_apply_seen()` read-modify-write `health-seen.json` under `ProcessLock("health-seen")` (two marks at once kept only one). Test: `test_system.py::test_two_marks_at_once_are_both_kept`.

- re74d3a46 `license.activate()` raises `LicenseError(code="bad_answer")` when the answer has no string `token`, before writing the key, the seat or the info (it was a KeyError -> 500 after `set_secret(KEY)`). Test: `test_license.py::test_activate_without_token_leaves_no_key`.

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
