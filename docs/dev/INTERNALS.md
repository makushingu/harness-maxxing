# Internal interfaces (between server modules)

Python modules call each other only through these functions. Keep signatures stable.

## maxxing.workspace  (owner: core)
- `topic_dir(path: str) -> Path` - validates a topic path (relative to the workspace, "" = root), raises ValueError.
- `list_topics() -> list[dict]` - `[{path, project, name, description}]` (projects/<p>/topics/<t>).
- `create_project(name, description="")`, `create_topic(project, name, description="")` -> dicts of API.md.
- `on_change(cb)` - `cb()` or `cb(change)` (sync or async) called after any project/topic create/update/
  rename/delete; `change = {action:"created"|"updated"|"renamed"|"deleted", kind:"project"|"topic", path, old_path}`.
  A rename already remaps session paths, Claude transcripts and `telegram.threads/sessions` keys.
- `project_emoji(project) -> str`, `set_project_emoji(project, emoji)`, `check_emoji(value)` - one emoji per
  project in `projects/<p>/.maxxing.json` (moves with the folder; in `backup.ALWAYS`).
- `move_to_trash(path, label=None) -> Path` - shared trash (state_dir('trash'), `.json` sidecar with the origin).

## maxxing.sessions.service  (owner: core)
- `list_sessions(path: str | None = None, archived: bool | None = None) -> list[dict]` (API.md Session)
- `get_session(sid) -> dict | None`
  Both read metas through `store.read_cached(sid)` (parsed meta kept per file (inode, mtime_ns, size); shared
  dict, never mutate it).
- `create_session(path, message=None, title=None, model=None, attachments=None, source="web",
                   notify=False, cron=False, env=None, timeout_s=None, auto_title=False) -> dict`
   `env` = extra environment for the turn (dict), `timeout_s` = max turn duration (stop after). `auto_title`: the
   caller made `title` from the first message (Telegram) - it is shortened like a missing title (sessions.titles).
- `send_message(sid, text, attachments=None, source="web") -> {"queued": bool, "session": dict}`
- `stop(sid) -> None` - signals the meta `pid` only while a runner holds the session's run lock
  (`store.runner_alive(sid, {})`): a dead runner's pid may belong to another process. `_enqueue` resets `pid` to
  None when it spawns a runner. The runner clears its stop / steer flags inside `_pop`'s locked edit, so a signal
  sent for the turn it just popped is never wiped.
- `read_events(sid, offset=0) -> (list[event], next_offset)` - normalised events (API.md).
- `end_offset(sid) -> int` - offset after the last complete line of the log (where the next turn's events start).
- `read_back(sid, end=None, limit=200) -> {events, start, next, more_before} | {reset: True}` - backward
  reading (tail / "show earlier"), never loads the whole log. `offset_valid(sid, offset)`, `log_ident(sid)`
  (inode, size) detect a rewritten log; `meta_ident(sid)` (inode, mtime_ns, size) of the meta file lets the
  session stream skip reading anything on quiet ticks. `compact_log(sid, dry_run=False)` clips an existing log (sessions/clip.py: tool outputs, `system/init` reduced
  to `INIT_KEEP`, `DROP_SUBTYPES` lines removed - the runner applies the same at write time).
- `last_assistant_text(sid) -> str`
- `on_turn_end(cb)` - `cb(session: dict, result: dict | None)` is awaited/called on the event loop when a
  turn of ANY session finishes, whatever started it (web, Telegram, cron). Fired per turn (the turn counter
  grows, or running -> error); turns ending within the same ~1 s scan are reported once. `result` = last
  normalised `result` event of the turn (None if the turn produced none). The watcher stamps its last pass in
  `<state>/session-watcher.json` `{at}` (every `PASS_STAMP_S` = 5 s, and at once after reporting): its first pass
  after a start reports the turns whose `finished_at` is later (they ended while the server was stopped or
  restarting); without that file (first start) the first pass is only a baseline.
- `wait_turn(sid, timeout_s) -> dict` - blocking helper (thread) used by `maxxing cron run`: returns the
  Session once it is not running and its queue is empty (or when the timeout expires).
- `move_session(sid, path)` (also `update_session(..., path=)`) - another topic for an idle session; moves the
  Claude transcript (`~/.claude/projects/<slug of cwd>/<csid>.jsonl`) so `--resume` keeps the conversation.
  Session meta also has `favorite` (Favorites block, copied by `handoff`).
- `handoff(sid)` creates the continuation with meta `handoff_pending` (time.time()): while it is younger than
  `HANDOFF_HOLD_S` (600 s), `_enqueue` queues messages without starting a runner (`queued: true`). The old
  session's runner (`Runner._handoff` -> `_start_target`) drops the flag, puts the summary seed at the HEAD of the
  queue and starts the runner; a failed or stopped summary drops the flag and starts the queued messages. The session
  watcher (`_scan`) calls `release_handoff(sid)` for a continuation whose hold expired with messages queued (the
  summary never came: its runner died).
- Also: `update_session`, `delete_session`, `clear_queue`, `compact`, `handoff`, `mark_seen`, `search(q)`,
  `models()`, `uploads_dir(path)`. Blocking functions raise `SessionError(status, code, message)`.
- Compaction in the runner (`sessions/runner.py`): `_auto_compact` after a turn above `auto_compact_tokens`; idle
  compaction in `_pop` - `_idle_compact(meta, item, cfg, now)` returns `(away, k_tokens)` when a `user` item (not
  cron/system source, steer, plan approval) pops for a non-fresh, non-cron session whose last call
  (`max(finished_at, cache_at)`; `cache_at` = last side question, it warms the thread too) is older than
  `idle_compact_after_s` with `context_tokens >= max(idle_compact_tokens, IDLE_COMPACT_MIN)`, unless
  `context_tokens - base_tokens` (meta `base_tokens` = context of the first call of the current thread, i.e. its
  fixed part) is under half of that threshold - a summary would save nothing. The message goes back
  to the queue head marked `held: true` (removed when it pops) and a `compact` item (`auto`, `idle`) runs first; `_post`
  then puts the seed into the message as `preface` (prepended by `build_prompt`, not displayed) instead of a separate
  seed turn. `service.stop` keeps `held` items: a Stop cancels the summary only, the message then runs.
- A successful turn of a `cron=True` session archives it; a message from the web/Telegram clears the flag.


## maxxing.sessions.titles  (owner: core)
- `schedule(sid, current, message) -> Thread | None` - called by `create_session` when no title was given and the
  message is not empty; nothing when config `short_titles` is false (or env `MAXXING_SHORT_TITLES=0`, set by the
  tests). Daemon thread, at most two calls at a time.
- `first_message(sid, message) -> Thread | None` - called by `send_message`: a session created automatic-titled and
  without a message carries meta `title_auto` (= that title); the first message pops it and, if the title is still
  it and the switch is on, sets `provisional(message)` and schedules. Later messages: one cached meta read, no write.
- `refine(sid, current, message) -> str | None` - `heuristic(message)`, or `ask_claude(message) or heuristic(message)`
  with config `short_titles_model` (default false: a call per new session counts in the Claude plan), written under
  `store.edit` only if the title is still `current` (the provisional one), then `bus.invalidate("sessions")`.
- `ask_claude(message) -> str | None` - `claude -p --output-format json --model claude-haiku-4-5-20251001 --tools ""
  --no-session-persistence --strict-mcp-config --system-prompt …`, stdin = first 1000 chars, cwd
  `<state>/claude-titles`, env `spawn.claude_env(None, "default")`, timeout 30 s; answer through `clean()`.
- `heuristic(message) -> str` - first sentence, leading FR/EN filler removed, cut at 40 chars on a word.
- `provisional(message) -> str` - first 60 chars (+ "…"): the instant title, and the title when the switch is off.
- `pending(sid) -> bool` - a short title is being made (between `schedule` and the end of its thread) or meta
  `title_auto` is set: the Telegram sync waits for it (60 s at most) before creating the session's thread.
## maxxing.claude_auth  (stdlib only, also used by the runner)
- `record(ok, error=None, source="turn"|"test"|"check")` - outcome of a real call; `detect(text) -> str|None`
  finds a sign-in error; `status() -> {ok, method, detail, checked_at, error}` (GET /api/claude/status `auth`,
  health, doctor); `needs_check()` - no verification in the last 6 h (background check in api/claude.py).

## maxxing.auto_update
- Harness updates itself while nobody uses it. Off by default (config `auto_update`, Settings -> System -> Updates,
  `PUT /api/system/auto-update`, `auto_update` in GET /api/system/version). Loop started by `api/system.py`
  `startup()` (only the installed server: `claude_update.runs_here()`; first pass `MAXXING_AUTO_UPDATE_DELAY` s,
  default 900; one `tick(spawn)` every 30 min).
- `tick() -> off|not_on_branch|pending|busy|unavailable|up_to_date|needs_review|tried_recently|started`. Never on
  a detached HEAD (`on_branch()`: a branch under test, put there on purpose) nor while `customs.pending()` (a
  conflict or a rolled-back version waits for a person: not retried every day). Waits while `busy_reason()`: a
  browser holds `/api/stream` (`bus.browser_count()`, signed-in streams only), or `claude_update.busy_reason`
  (turn, queue, cron job, side question, last turn < 10 min ago), or the `maxxing-update` unit runs. Then
  `smartupdate.preflight()` (fetches): only the verdict "simple" with no upgrade note, no unsaved change and every
  customization "ok"/"included" goes on; anything else posts one notification per target (`needs_review`). One try per
  target per 24 h (`<state>/auto-update.json` `tried`); busy is checked again after the preflight. The update is
  `api/system._spawn_update(smart=False)`: the usual `maxxing update` (rolls itself back when the new version does not
  start) without the Harness session of the Update button.

## maxxing.claude_update
- Claude Code updated while the server is idle (turns run with its own update check off: quiet start). Loop started by
  `api/claude.py` `startup()` (`start()`/`stop()`; only the installed server runs it - `runs_here()`: MAXXING_STATE is
  `/var/lib/claude-maxxing`, a dev server or a test copy of the state never updates the machine's CLI unless
  `MAXXING_CLAUDE_UPDATE=1`; off everywhere with `MAXXING_CLAUDE_UPDATE=0`, first pass after
  `MAXXING_CLAUDE_UPDATE_DELAY` s, default 600), one `tick()` every POLL_S (300 s) in `asyncio.to_thread`.
- `tick(now=None, force_check=False) -> "off"|"not_installed"|"unknown"|"up_to_date"|"unsupported"|"busy"|
  "failed_recently"|"updated"|"failed"`: registry read (`latest_version()` = `depcheck.claude_stable`, the npm
  `stable` dist-tag) at most every CHECK_EVERY_S (6 h); no `claude --version` between checks when nothing is pending.
  Newer, `install_method()` known (native `claude install <v>` / npm `npm install -g --prefix <p>`; else
  "unsupported"), `busy_reason()` None and the exclusive flock `<state>/.claude-update.lock` taken (a turn's runner
  holds it shared while its claude runs, `runner._claude_in_use(note)`, waiting at most UPDATE_WAIT_S = 7 min with an
  `mx_note` in the session, and a `warn` note when it gives up and starts anyway) -> `run_update(v)` (5 min
  timeout) then `installed_version()` again; a version that does not start is reinstalled back
  (`run_update(previous)`); unchanged version = failure. A failed
  version waits 6 h. Feed `system` item on success; on failure once per version (`dedupe`).
- `busy_reason(now=None) -> str|None`: a session `running`, a queue on a session not in `error`, an `aside`
  question, a cron lock held (`crons.is_running`), or the newest `finished_at` less than IDLE_AFTER_S (600 s) ago.
- State `<state>/claude-update.json`; `public()` = GET /api/claude/status `auto_update`; config `claude_auto_update`.
- Off by default (config `claude_auto_update` false). Tests monkeypatch `installed_version`, `latest_version`,
  `run_update`, `install_method` (never a real update).

## maxxing.telegram.gateway  (owner: connectivity)
- `alert(text, loud=False)` - sign-in alerts thread (no-op when not configured). Thread-safe.
- `notify_topic(path, text)` - message in the main chat (topics have no thread; sessions do).
- Thread names: `session_label(s)` = `"[<emoji> ]<project>/<topic> · <title>"`, `topic_label(path)` =
  `"[<emoji> ]<project> / <topic>"` ("Where?" buttons, messages).
- Session threads: `config.telegram.session_threads[sid] = {tid, name}`, kept in sync by
  `sync_threads_with(call, probe)` (open sessions = `open_sessions()`: human, not archived, active in
  the last `thread_days` days, <= MAX_THREADS); triggered by the bus topic "sessions" (`bus.subscribe`)
  and every RECONCILE_EVERY s. Older layout (one thread per topic) migrated by `_migrate_topic_threads`.
  Telegram has no silent "does this thread exist" call (editForumTopic without a change succeeds on
  a deleted thread; with the same name it posts a service message): deleted threads are found on
  the next send / rename (`_forget_thread` / `_thread_gone`) and are reopened (`Gateway.reopen_thread`).
  A session that left the list keeps its mapping when `deleteForumTopic` fails for a transient reason: network
  errors and 429 stop the pass, 5xx skip the session; both are retried at the next sync. Success, `_thread_gone`
  and other 4xx (no right to manage topics, bot removed) drop it (a refusal is not retried at every sync).
  `mirror_web()` (opt-in: `mirror_web` and `mirror_web_chosen`): `on_turn_end` without a pending Telegram turn copies the web turn into the thread
  (`service.last_user_message` + the answer, silent unless `notify`).
- `notify_cron(text)` - plain message in the "Crons" thread. `notify_cron_report(header, body, markdown, loud)` - a
  cron run's report: bold header + the Claude answer rendered by `fmt.render` (from its start, `fmt.head` at
  `REPORT_MAX` = 12000) or command output in `<pre>` (`fmt.code`); body packed with room for the header.
- `status() -> dict` - the GET /api/telegram payload.
- `start()/stop()/restart()` (async, server loop) and `install_hooks()` (registers
  `sessions.service.on_turn_end` + `workspace.on_change`), called by maxxing.api.telegram.
- Uses from sessions.service: `create_session`, `get_session`, `list_sessions`, `send_message`, `stop`,
  `update_session(sid, model=…)` (/model), `read_events` / `end_offset` (progress mode), `last_assistant_text`, `models()`.
  These are called from worker threads (`asyncio.to_thread`) and must be thread-safe.

## maxxing.feed / maxxing.feedhooks  (owner: organisation)
- `feed.post(title, body="", level="info", source="custom", url="", dedupe=None, group=None, notify=True) -> dict | None`
  (None = duplicate). Usable from any process (sqlite WAL `<state>/feed.db`); the server's `api/feed` watcher turns
  outside writes into the bus topic "feed". `feed.system(...)` = same, never raises (built-in events: `crons._feed`,
  `cmd_core.notify_update` / `_notify`, `api/auth._alert`).
- `feed.rule_for(source, level)`, `settings()` / `save_settings(telegram, rules, hooks)` (config `feed`).
- `feedhooks.create/update/remove/test`, `deliver(token, headers, body) -> (status, json)`, parsers per kind
  (`PARSERS`); tokens + secrets in secrets.json `feed_hooks`. `SIGNED_KINDS` (stripe, shopify, github) need a
  secret to accept deliveries (`401 secret_required`, feed.system warning grouped `hook-secret-<id>`); creating
  one without a secret stays allowed (Stripe shows its whsec only once the endpoint URL exists).
  `BODY_DEDUPE` (shopify, github): their delivery-id headers are not covered by the signature, so `deliver` replaces
  the parser's dedupe with `_replay_key` = `sha256:<topic>:<sha256(body)>` (Shopify: a known topic of
  `_SHOPIFY_TOPICS`, else `other`; GitHub: no topic). Stripe signs a timestamp (5 min tolerance) and keeps the event
  id. `feed.post` turns the unique-index `IntegrityError` of a concurrent identical dedupe into a duplicate (None).
- Telegram `Gateway.authorized(chat, user)`: chat == `telegram.chat_id` AND user in `telegram.user_ids` (an empty
  list authorizes nobody; `_try_link` always records the linking account and refuses a message without `from`).
- Telegram: `gateway.feed_notify(ev, loud)` / `feed_message(ev)` (body cut at 700 characters BEFORE HTML escaping); thread key `#feed` (`NOTIFY_ONLY` = Crons, Alerts,
  Notifications: never treated as topic threads by the legacy migration); callback `f:<id>` = Ask Claude.

## maxxing.backup  (owner: connectivity)
- `run() -> dict`, `restore(ref=None) -> dict`, `restore_from(repo, token, ref=None)`, `status()`,
  `history(limit)`, `last_success_age_h() -> float | None` (health check).
- Schedules itself through maxxing.crons (`list_jobs/create_job/update_job/delete_job`, job name
  "Memory backup", shell command `<maxxing> backup run`).
- Restore on a server in use: the ids of the extensions whose code files (`.py .js .mjs .html .htm`) it will write
  are added to config `extensions.disabled` BEFORE any file is written, all inside `extensions.publishing()` (the
  lock `extensions.scan()` / `set_enabled()` hold while they check the flag and import: thread RLock + flock on
  `state/extensions.lock`, so the CLI restore and the server exclude each other); a restored `extensions` setting
  keeps them in its disabled list.

## maxxing.voice  (owner: connectivity)
- `settings() -> dict`, `update_settings(**kw)`, `status() -> dict` (GET /api/voice), `readiness() -> (ready, reason)`.
- `transcribe_file(path, language=None, engine=None) -> {text, language, duration_s, engine, model, ms}` - blocking
  (call through `asyncio.to_thread`): ffmpeg → 16 kHz mono WAV (`normalise`, max 15 min) → engine. One transcription
  at a time (process lock). Raises `VoiceError(status, code, message)`.
- Engines in `_ENGINES` (`local` = faster-whisper int8 CPU, lazy-loaded once, unloaded after 10 min idle; `groq` /
  `openai` = httpx multipart, Opus-compressed upload, keys from the vault). Tests replace `_ENGINES[...]`,
  `install_steps[...]` and `http_transport` (httpx.MockTransport).
- `start_install(model=None)` (background thread: `uv sync --frozen --no-dev --extra voice` in `server/`, then the model
  download in a child process; progress = size of `state_dir('voice/models/<m>')`), `download_model(name)`,
  `delete_model(name)`, `sync_extras()` (flags added by `maxxing update` so the optional group survives updates:
  marker `state/voice/extra-installed` or engine `local`), `doctor()`.
- Used by maxxing.api.voice, maxxing.telegram.gateway (`_voice`), cmd_core (doctor, update), cmd_voice (CLI).

## maxxing.health  (owner: organisation)
- `collect() -> dict` - the GET /api/system/health payload (cached 30 s).
- `services(force=False)` - GET /api/system/services: ONE `systemctl show <all units>` (blocks split on blank
  lines, matched by `Id`), cached 10 s; `invalidate_services()` after a start / stop / restart.

## maxxing.security (session cookie)
- Cookie `mx_session` = `<issued_at>.<nonce>.<hmac_sha256(cookie_key, "<issued_at>.<nonce>")>` (legacy
  `<issued_at>.<hmac>` from <= 2.0.0a31 still accepted), lifetime `COOKIE_MAX_AGE` = 30 days.
- `revoke_cookie(value)` (sign-out) stores `sha256(value)[:32] -> issued_at + COOKIE_MAX_AGE` in secrets.json
  `revoked_sessions`; expired ids are pruned on each sign-out. Past `REVOKED_MAX` (500) ids the list is dropped
  and `sessions_not_before = now + 1` is set instead (cookies issued earlier are refused). `set_password` rotates
  `cookie_key` and clears `revoked_sessions` and `device_key` (two-step sign-in: every browser asks again).
- Preview tokens (`api/filesite.py`) are signed with `cookie_key` and carry `i` (issue time) and `s` (session id):
  `read_token` refuses them when `s` is revoked or `i < sessions_not_before` (a token without `i` is refused).
- `StreamAuth(cookie).ok()`: the SSE streams' re-check before each frame (`bus.stream(cookie)`, `api/sessions._sse`):
  one stat of secrets.json while its (inode, mtime, size) is unchanged, else / every `RECHECK_S` (15 s) / past the
  cookie's expiry a full `cookie_valid`.
- `streamcap.py` (audit F01): both SSE endpoints answer through `stream_response(cookie, factory)`: a slot per
  sign-in (`security.session_id`) is taken before the body generator is created, `PER_SIGNIN` 24 / `TOTAL` 96, else
  `429 too_many_streams` + `Retry-After`; `CappedStream.__call__` gives the slot back however the response ends (also
  when the generator never started), a `weakref.finalize` if the response is never sent. `counts()` for tests.

## maxxing.bodylimit / maxxing.uploads (request bodies)
- `bodylimit.BodyLimit` (ASGI, outermost but the security headers): every non-multipart POST/PUT/PATCH/DELETE under
  /api/ is decided from its headers before the body is read - no valid cookie on a non-public route -> 401; public
  `/api/auth/*` -> CSRF header first, then `PUBLIC_MAX` (64 kB); `/api/hooks/*` -> `feedhooks.MAX_BODY`; signed in
  -> `DEFAULT_MAX` (1 MB) or the cap of the first matching `ROUTES` entry. `Content-Length` over the cap -> 413
  before reading; a chunked body is counted by the wrapped `receive()` (413 as soon as it goes over).
  `cap_for(method, path, authed)` is the table lookup. A route whose JSON grows past 1 MB must get a `ROUTES` entry.
- `uploads.UploadGuard`: multipart bodies (auth + CSRF, `upload_max_mb`, temp-dir room) - see API.md Conventions.

## maxxing.twofactor (two-step sign-in with Telegram)
- On = config `telegram.two_factor`; effective (`enabled()`) only with a token, a chat and its owner
  (`available()`). `gateway.forget()` and a new bot drop the flag. `set_on(False)` also calls `forget_devices()`.
- Challenges in memory (one server process): `start(purpose, ip, ua)` (blocking: Telegram `sendMessage` to the
  Alerts thread, HTML, buttons `a:<id>:y|n`; `Refused("throttled"|"two_factor_unavailable")`), `check(id, code)`
  (approved = consumed once; `CODE_TRIES` wrong codes kill it), `decide(id, allow)` from `Gateway._on_callback`
  (kind `a`, after `authorized()`). The message is edited (buttons removed, outcome added) in a daemon thread.
  `TTL` 120 s, `GRACE` 60 s to collect an approval, `NEW_MAX` 5 per client / 15 min, `PENDING_MAX` 10.
- Trusted browser: cookie `mx_device` = `<issued_at>.<nonce>.<hmac(device_key)>`, path `/api/auth`, 30 days;
  `forget_devices()` = `device_key` -> None (recreated on first use).
- CLI `maxxing 2fa status|off|forget-browsers` (`cmd_twofactor.py`): the way back in when Telegram does not answer.

## maxxing.bus
- `invalidate(*topics)` - thread-safe UI invalidation (see API.md Global bus).

## maxxing.config
- `load_config()/update_config(**kw)/get_secret/set_secret/set_secrets (several in one write)/read_json/write_json/state_dir/workspace()`.
  `load_config()` keeps the merged result (pickled) while config.json's (inode, mtime, size, ctime) and the
  defaults are unchanged and returns a fresh copy each call (callers may change it); saves are atomic renames,
  so a write by any process is seen on the next call.
- User secrets (Keys vault) live in secrets.json under `"vault": {name: {value, note, expose, updated}}`.
  `config.exposed_env()` (owner: organisation, in maxxing/vault.py) -> dict of secrets flagged `expose`,
  merged into every Claude turn's environment by the runner spawner (sessions/spawn.py currently reads the vault
  itself - same result) and into shell cron jobs.

## maxxing.crons  (owner: organisation)
- `run_job(id) -> Run | None` (blocking; None = unknown or already running) · `spawn_run(id)` · `sync_crontab()`
- `list_jobs()`, `read_runs(cron_id=None, limit=50)`, `last_runs() -> {cron_id: Run}`, `parse/humanize/next_runs`.
  The run history is parsed once per file version (`_all_runs`, keyed on path + mtime + size); `read_runs`
  returns copies.
- While a job runs, its lock file (`<state>/crons/locks/<id>.lock`) holds `{"pid", "at", "pgid"}`; a normal end
  empties it. A run killed before its end (SIGKILL, out of memory) leaves it: the next `run_job` kills the orphan
  job shell (`pgid`), records a failed Run (`code -9`, "interrupted: …") and reports it.
- Claude jobs call `sessions.service.create_session(..., source="cron", cron=True, env={MAXXING_CRON_ID, MAXXING_CRON_NAME},
  timeout_s)` (or `send_message` when `reuse_session`), then `wait_turn` + `last_result` + `last_assistant_text`.
- Job units: `spawn_run(id)` ("Run now", and `maxxing cron run <id> --detach` = what every managed crontab line calls)
  starts `python -m maxxing cron run <id>` in `systemd-run --collect --unit maxxing-cron-<id> --slice=maxxing-jobs.slice`
  + `memory_properties()` + `RuntimeMaxSec=<timeout_s + KILL_GRACE_S + 120>` (backstop if the run itself dies). The
  unit runs the job inline (`run_job`: per-job flock, no overlap; a second start while the unit exists ->
  `already_running`, exit 3). When the main process ends, systemd kills what the job left in the unit (default
  KillMode=control-group): background processes of a job end with it, as with "Run now" before. `units_available()`
  = not `MAXXING_SPAWN=direct`, `systemd-run` on PATH and `/run/systemd/system` (`SYSTEMD_DIR`); otherwise
  `--detach` runs the job in the cron process and "Run now" starts a detached subprocess.
- `maxxing-jobs.slice` (`cmd_core.ensure_jobs_slice`, called by every `maxxing init`, so by every update; removed by
  uninstall): `/etc/systemd/system/maxxing-jobs.slice` with `MemoryMax=<jobs_memory_max>` (config, default `75%`;
  `""`/`infinity` = no line) = the memory budget of all jobs running at once; written only when the text changed
  (then daemon-reload); skipped without systemd and with MAXXING_SPAWN=direct. Claude jobs run their turn in a turn
  unit (outside the slice; capped by `unit_memory_max`), only the waiting `cron run` process is in the slice.
- Shell jobs: `bash -lc` in the workspace, env = os.environ + exposed vault + MAXXING_CRON_ID/NAME; exit 124 on timeout.
  Timeout (`_kill_group`): SIGTERM to the job's process group, then after `KILL_GRACE_S` (5 s) SIGKILL to the whole
  group unconditionally (bash may have exited while a child ignoring SIGTERM lives on; the group id cannot be reused
  while a member lives); early exit when bash is reaped and the group is empty. In a unit, processes that left the
  group (setsid) are killed by systemd when the run ends.
  Output: stdout+stderr into a pipe drained by a reader thread that keeps only the last OUTPUT_TAIL bytes (no temp
  file: /tmp is often a tmpfs); after the exit the reader gets 2 s (a background child may hold the pipe open).
- The managed crontab line is `<schedule> [MAXXING_STATE=…] MAXXING_CRON_DETACH=1 <maxxing> cron run <id> [--if-due]
  >/dev/null 2>&1`; `MAXXING_STATE=…` only when the state dir is not the default. The detach request is an environment
  variable, not a flag: a version restored by a rollback (a69 and older) does not know `--detach` and would refuse
  every line; it ignores the variable and runs the job inline. `cmd_cron` pops it (never inherited) and `spawn_run`
  never forwards it. `cron_keep_background` (true on installs that existed before a70) = scheduled runs stay inline
  (no unit: background programs live on, as in a69). `maxxing init` re-syncs the block.
- `split_crontab`: a BEGIN marker without END (edited by hand) keeps only the ` cron run ` lines as managed; every other
  line after it stays the user's.

## maxxing.shopify  (owner: organisation)
- Built-in widget `shopify` (widgets.BUILTINS): `card(force)` -> connect card, error card, or figures; `fetch(store, token, since)`
  (Admin GraphQL `orders`, 250/page, ≤ 4 pages, cancelled orders skipped) and `build_card(data, today, tz)` are pure enough to test.
  Keys from the vault: `SHOPIFY_STORE`, `SHOPIFY_ADMIN_TOKEN`. `MAXXING_SHOPIFY_API` overrides the base URL (tests, demo).

## maxxing.gitview  (owner: organisation)
Read-only git: `local_repos(refresh)` (walk of the files root, MAX_DEPTH 6, MAX_DIRS budget, PRUNE + dot folders,
8 threads of `summary()`), `resolve(path)` (inside the files root, climbs to the clone), `graph(path, limit,
branches)` (`git log --branches --remotes --tags HEAD --topo-order --decorate=full`), `commit(path, sha)`
(`--numstat --diff-merges=first-parent`); every git call: no shell, `-c safe.directory=*`, GIT_TERMINAL_PROMPT=0,
GIT_OPTIONAL_LOCKS=0, 10 s. GitHub (`_gh(path, params, tok)`, MAXXING_GITHUB_API): `tokens()` (vault values matching `GH_TOKEN_RE` under any name + GITHUB_TOKEN/GH_TOKEN + backup `github_token`, deduped by value), `github_repos` (per token /user + /user/repos ≤ 500, in parallel, merged by full name with the best permission, `keys`/`accounts`; fills `_access` = repo -> tokens best first; refused tokens in `errors`), `_gh_repo` (tries `_access` tokens then the rest, prefers not_found over bad_token),
`github_graph` (branches + commits per branch merged, `_topo` = children before parents, newest first),
`github_commit`, `github_pulls`. `overview()` joins clones and GitHub repos (`local_paths`). 60 s cache per
listing (`clear_cache()` in tests). Web: `features/git/` (GitGraph = lane layout + SVG, GitBlock = ```git in
`components/ui/markdown.tsx`, lazy; GitPage = route `/git`, shown in the nav by `useNav()` when settings `git_page`).

## maxxing.team  (owner: organisation)
Chats between people, `<state>/team/team.json` (format in the docstring), one lock (`_lock`), atomic writes, bus
topic `team`. `state()`, `messages(cid)`, `create_chat`, `send`, `react`, `create_poll`, `vote`, `mark_read`,
`mark_sent` (a "to a session" click), `edit_message` / `delete_message`, `update_group` / `leave_group` / `set_muted`,
`typing` and the read receipt (signals through `teampeer.signal_all`, never queued), `summarize(cid, ids, since)` (one `claude -p` without tools, Sonnet,
prompt `SUMMARY_PROMPT`, titles in the chat's language). Every local change is `_broadcast` to the other members
through `teampeer.send` (message `pending` = ids not reached yet, cleared by `delivered()`); remote events come in
through `apply_remote(frm, contact, event)` which checks membership and authorship; their messages keep `recv`
(arrival time here, unread counts on it) and an `at` never in the future. People ids = `teampeer.pid(address)`;
the user is `ME`. Numbers from peers go through `_finite`; a group roster is stored only if we are in it.
Web: `features/team/` (page `/team`, right panel `TeamPanel`, `Live.tsx` presence + notifications, `SendTo.tsx` from
the session message menu).

## maxxing.teampeer  (owner: organisation)
Server-to-server transport, stdlib + httpx, protocol in the docstring. `<state>/team/peers.json` (600): peers,
invites (the code, 15 min), shared files, outbox. `readiness()` (public https address, not Tailscale / private),
`create_invite`, `join`, `hello` (public side; 409 for an address already linked: an invitation never replaces a
key), `answer`, `forget` (a member of shared groups stays as `group`), `verify(request)` -> (sender, scope: "" =
contact key, else the one group its key is for; signature, time ±300 s and not before `_STARTED` (the nonce cache is in memory), rate limits on
`security.client_key`), `receive(frm, event, scope)` (a group key: message / vote / react of that group only),
`add_group_peer` (never for a contact or a request), `send(addresses, event, msg)` -> outbox, worker `start()` /
`_outbox_round()` (`RETRY` backoff, `OUTBOX_DAYS`; a failing address waits, the others go; no key = dropped),
`share_file` / `file_for` (scope checked) / `fetch_file` (signed GET, ≤ `upload_max_mb`, keeps
`upload_min_free_mb` free, `FETCH_DEADLINE`; `team._fetch` reserves the name, 4 downloads at a time).
Outgoing calls go through `_http()`: `_PublicBackend` resolves the name once and connects to that IP, refused
unless public (no DNS rebinding to a local address). `team_insecure` / MAXXING_TEAM_INSECURE=1 allows http and local addresses (tests only).

## maxxing.infra  (owner: organisation)
- `probe.py`: stdlib-only, Python >= 3.8, one JSON on stdout; run locally as a subprocess and remotely with
  `ssh -o BatchMode=yes ... host python3 - '<opts>'` (script on stdin). Sections (each fails alone into `errors`):
  `server` (os, ips without docker/veth, mem, disk, load), `listeners` (`ss -ltnpH` -> unit from /proc/<pid>/cgroup,
  cwd, `repo_of` = .git/config origin without credentials), `containers` (`docker ps` json, compose labels),
  `sites` (`parse_caddy` = admin API `/config/` or `caddy adapt`; walks subroutes, `vars root`, `rewrite
  strip_path_prefix`, sandbox CSP header; a static path site's folder = root + path unless stripped; `parse_nginx`),
  `databases` (native postgres via `runuser -u postgres -- psql`, docker postgres via `docker exec psql -U
  <POSTGRES_USER>`, mysql by socket, redis/mongo listed, SQLite by magic bytes under roots with a 6 s budget),
  `buckets` (Garage admin API v2 with the token of /etc/garage.toml).
- `providers.py`: Cloudflare (`_CF.get/all`, a 10000/9109 error -> `missing_permission` for that section only;
  DNS per zone; `cf_point(host, ip)` creates an A/AAAA, DNS only), Hostinger (`/api/domains/v1/portfolio`,
  `/api/vps/v1/virtual-machines`, `/api/dns/v1/zones/<d>`), RDAP. Bases: MAXXING_CLOUDFLARE_API,
  MAXXING_HOSTINGER_API, MAXXING_RDAP_API.
- `build.py`: probes + providers + rdap + registry -> resources and links (upstream port -> listener -> unit /
  container / repo; host -> domain (longest suffix); DNS A/AAAA content -> server by IP (`dns_elsewhere`); Hostinger
  VPS merged into a registered server by IP; project from `<workspace>/projects/<p>/` paths; registry annotations;
  declared but not found -> `missing`).
- `__init__.py`: `refresh()` (lock, probes + providers in parallel, RDAP once a day for at most 25 domains, `run_checks`
  = GET of each URL without redirects + TLS expiry per host, 16 threads; `check_url` streams the response and closes it
  after the status line and headers (never the body; h11 caps headers at 16 KiB) and a watchdog shuts the socket down
  after `CHECK_TOTAL_S` = 10 s in total; proxy/worker 4xx = alive; backups.json;
  `_alerts` vs the previous snapshot -> feed source `infra`, group per incident, dedupe per cert/domain threshold),
  `mark_stale()` (CLI recipes: the server loop refreshes within a minute), `view()`. MAXXING_INFRA_CHECKS=0 skips
  the network checks (tests).
- `registry.py`: `<workspace>/infra.json` `{servers, resources:{id: {declared, kind, name, project, note, hidden,
  recipe, vault_keys, urls, details}}}` - no secret ever. A server = `{name (in the resource ids, never changes),
  label (shown, renamed at will), host, user, port, key}`; `free_name()` = short host name, made unique.
- `platforms.py`: Vercel (`/v2/teams`, `/v10/projects`, `/v5/domains`, per team), Netlify (`/sites`, `/dns_zones`),
  Supabase Management API (`/v1/projects`, `.../storage/buckets`, `.../functions`), GitHub Pages (`/user/repos`
  has_pages + `/repos/x/pages`, every token of `gitview.tokens()`). Same normalised shape for all
  (`sites|databases|buckets|functions|domains`), sections fail alone; `VERIFIED` (empty) = seen on a real account,
  the others are `beta` in `source_state()`. Written from the official OpenAPI documents; tests use their shapes.
- `dnsinfo.py`: public DNS over DoH JSON (`MAXXING_DOH_API`, default Cloudflare), cache `<state>/infra/dns.json` 6 h,
  80 names a refresh (`build.hosts_to_resolve`: domains + www + custom site hosts); `dns_provider` from NS suffixes,
  `hosted_by` from CNAME suffixes then IP ranges (Cloudflare proxy last). build.py: public A records fill `records`
  when no zone was read, so sites/domains link to our servers (`hosted_by: "server"`) for any registrar.
  Registry `domains: [...]` = domains added by hand (source `added`).
- `connect.py`: Harness SSH key `<state>/ssh/infra_ed25519` (made on first need, dir 700). `auto_connect()` (in
  `refresh()`, after the providers): a running Hostinger VPS whose root keys (API `GET .../virtual-machines/<id>/ssh-keys`)
  include one of `~/.ssh/*.pub` or the Harness key, and whose IPs no registered server has, is registered (label
  "VPS Hostinger"); one look per VPS every 6 h (`<state>/infra/autoconnect.json`); no blind key tries (fail2ban).
  `connect_hostinger()` (button Connect): same, else `POST .../ssh-keys` with the Harness key then `ssh true` every
  5 s up to 60 s. `connect_host()`: Harness key, then the SSH defaults; else `need_key` + the line to paste.
- `caddy.py`: path site = `/etc/caddy/maxxing-paths/<name>.caddy` (`redir` + `handle_path` (or `handle` with
  --keep-prefix), CSP sandbox without allow-same-origin + `Access-Control-Allow-Origin *` so module scripts load from
  the opaque origin), imported inside `claude-maxxing.caddy` before `reverse_proxy` (install.sh writes the line since
  2.0.0a59, older installs get it added); host site = `/etc/caddy/sites/<name>.caddy` imported by the Caddyfile.
  `_apply`: write, `caddy validate`, reload, restore every file on failure. Reserved names = UI routes + web/dist
  entries. MAXXING_CADDY_DIR / MAXXING_CADDY_BIN / MAXXING_CADDY_RELOAD.
- `actions.py`: PostgreSQL (apt, localhost check, role refused if it exists, password via stdin, vault
  `DB_<NAME>_URL` not exposed, cron job "Infra: database backups" `30 3 * * *` `maxxing infra db backup`; dumps
  `pg_dump -Fc` + SQLite backup API into /var/backups/maxxing-db, 7 kept, state in `<state>/infra/backups.json`),
  Garage v2.1.0 (static musl binary checked against `GARAGE_SHA256` per architecture before it is installed,
  else `checksum_mismatch` and nothing written; `/etc/garage.toml` 600 with every port on 127.0.0.1, unit `garage.service`,
  single-node layout; bucket + own key, vault `S3_<NAME>_*`, `--public` = path site proxied to the web endpoint with
  `Host: <name>.web.garage.localhost`), `server_add` (probe first).
- API `api/infra.py` (loop: first run 60 s after start, then every minute checks period / stale), CLI `cmd_infra.py`,
  skill `maxxing-infra`. Web: `features/infra/` (InfraPage = route `/infra`, nav `useNav()` when `infra_page`;
  InfraBlock = ```infra in `components/ui/markdown.tsx`, lazy; bus topic `infra`).

## maxxing.mcp  (owner: organisation)
Claude Code owns the data: user scope = `mcpServers` of `.claude.json` (in `CLAUDE_CONFIG_DIR` when Harness has its
own Claude folder, else `~/.claude.json`), local scope = `projects[<abs folder>].mcpServers` (= one topic),
project scope = `<folder>/.mcp.json` (read; remove edits the file). Writes go through the official CLI
(`claude mcp add-json -s user|local`, `remove`) run with the turn environment (`spawn.claude_env()`) and the topic
folder as cwd; `.claude.json` is edited directly only for what the CLI cannot do (`on_workspace_change`: a renamed
project/topic moves its `projects` keys; removing a server of a deleted folder) and to put back the literal
secrets that `_add_json` leaves out of the `add-json` argument (visible in `ps`): the CLI gets `_redacted(cfg)`, then the
real config is written in place. States: `check()` runs
`claude mcp list` per folder in a thread (`parse_list`: `name: target - ✓|!|✗|⏸ detail`), kept in memory.
OAuth: `login_start` spawns `claude mcp login --no-browser -- NAME` on a pty, reads the authorize URL (OSC 8 links
unwrapped), `login_finish` writes the pasted localhost redirect URL + CR and waits for the exit code; one attempt
per server (a new one replaces it), expired after 15 min by `_gc()` (run by GET /api/mcp, login start / finish and
a reaper thread every 30 s while attempts exist). `_Login.close()` is idempotent and frees the pty fd only after
the CLI is dead and the reader thread has returned (a freed number is reused at once by other components).
Server names never start with `-` and follow `--` on the CLI. `${KEY}` references to vault keys flip them to
`expose` on add. Masking (API and backup): a header / env value is shown only when it is references (with an
optional auth scheme word) or a `PLAIN_HEADERS` header; URL userinfo and query values are masked. `export()` /
`restore()` = `_maxxing/mcp.json` of the memory backup (masked values blanked). Every mapping read from
`.claude.json` / `.mcp.json` goes through `_dict()` (hand-edited files). `.claude.json` rewrites use a unique
0600 temp file + `os.replace`.

## maxxing.pcbridge  (owner: organisation) - Browser of my PC
State `<state>/pc/devices.json` (0600): `device` (token kept as sha256), `pairing` (code hash, 15 min, single use),
`settings.idle_min`, `mcp_secret`, `cdp_secret`; `actions.jsonl` (last 500), `tools.json` (tool list cache), `bin/`
(agent binaries), `tools/chrome-devtools-mcp-<v>/` (npm `--ignore-scripts`, installed on first use).
Path of a tool call: Claude Code -> `POST /api/pc/mcp` (user-scope MCP `harness-pc`, type http, loopback + Bearer
secret) -> `tools_call` -> `Hub.get_child()` = `chrome-devtools-mcp` (stdio JSON-RPC, `CDM_ARGS`: performance /
emulation / memory / network categories off, no usage statistics) started with `--wsEndpoint
ws://127.0.0.1:<port>/api/pc/cdp` -> `Hub.channel()` opens a channel on the agent's websocket (`open` / `data` /
`end`) -> the agent's local DevTools socket. `ensure_browser()` sends `launch` first (40 s). Nothing runs until the
first call; `_idle_watch` (30 s) closes the browser (`close`) and stops the child after `idle_min` without a call;
an agent disconnect ends every channel and the child. `BLOCKED_TOOLS` (upload_file, screencast, lighthouse) and
unknown names are refused; the offline answer is a normal tool result (`isError`). One retry when the child dies
mid-call. Agent binaries: `MAXXING_PC_BIN_DIR`, else `bin/`, else the release in `pc_agent.json` (sha256 checked);
`personalised()` appends `<json><uint32 BE len>HMPCCFG1` (server, pairing code, browser, autostart).
`pc_tools.json` = the tool list shipped for `tools/list` before the first start.
Security boundaries: `pair()` stores a `candidate` (15 min); `WS /api/pc/ws` holds a candidate's socket
(`_wait_confirmation`, nothing relayed) until `confirm()`, else sends `unpair`. `tools/list` drops `filePath` /
`sourcePath` (files of this server), `tools_call` drops them too and refuses a `url` that is not http(s) /
about:blank / data. The authoritative check is in the agent (`pc-agent/cdpfilter.go`): every DevTools command is
filtered (downloads, file inputs, drag of files, permissions, PWA / Extensions, non-page URLs). `actions.jsonl` keeps
URLs without query / fragment / userinfo. A channel with more than 64 MB waiting for the local socket is ended.

## maxxing.customs  (owner: core)
- Customizations = local commits on top of `origin/<branch>` in `config.CODE` (subject `custom: <title>`, trailers
  `Custom-Id`, `Why`, `Saved`). Git is the source of truth; `export()` rewrites `<workspace>/CUSTOMIZATIONS.md` +
  `customizations/NNNN-*.patch` (format-patch, in the backup ALWAYS list).
- `list_customs()`, `save(title, why, files)` (refuses `web/`), `drop(id)`, `restore(dir)` (`git am -3`, idempotent by
  Custom-Id), `dirty_files()`, `summary()`, `ensure_identity()` (local git user for commits/rebases).
- Pending update state: `<state>/update/pending.json` `{at, reason: conflict|health|dependencies, from, target,
  target_version, customs, conflicts}`; `refs/maxxing/pre-update` = code before the last update (rollback point).
- `cmd_core.cmd_update`: read the rollback point (HEAD + current branch, before any `--branch` checkout) -> fetch ->
  stash web/ edits -> auto-save dirty edits -> ff (no customs) or `git rebase origin/<branch>` ->
  conflict: abort + `_back_to(old)` + pending, exit 3 -> `_update_finish`: uv sync (fail: rollback, exit 4), init,
  export, restart + `_healthy(version)` (fail: rollback + restart, exit 4). `_back_to(old)` = checkout the start
  branch, `reset --hard old`, pop the web/ stash. `--resume` runs `_update_finish` from pending.from; `--rollback`
  resets to `refs/maxxing/pre-update` and refuses (exit 1, nothing changed) while the code directory has uncommitted
  changes. The branch that ran at that point is kept in `<state>/update/pre-update-branch.json` `{commit, branch}`
  (`""` = detached HEAD): `_back_to`, `--resume` and `--rollback` check it out (or detach) before the reset, so
  the branch an update switched to (or main, from a detached test checkout) is never rewritten.

## maxxing.smartupdate  (owner: core)
- `preflight(branch=None, fetch=True) -> Preflight`: `git worktree add --detach <state>/update/mx-preflight-*/code
  <target>`, then `cherry-pick --no-commit` of each customization: conflict / empty (= included) / applied (+ overlap
  with `git diff base..target` = review). Never touches the install; cached in `update/preflight.json` keyed by
  [HEAD, target, dirty files]. Extensions vs the target's `EXT_API_MIN..EXT_API` (read with `git show`); upgrade
  notes of the target that ask something (first paragraph not "Nothing to do").
- `verify() -> report` (`update/report.json`): `extensions.scan()`, `widget_card(force)`, `node --check page.js` when
  node exists, each customization's `check` (shell, cwd workspace, `MAXXING_CODE`, 60 s).
- `mark_updated(from, to, smart)` (end of `maxxing update`) -> `update/after.json`; `after_update()` runs once at
  server start (api/system.startup, after `MAXXING_AFTER_UPDATE_DELAY` s): verify, feed alert if broken, and for
  `smart` the upgrade-notes session (config `update_auto_notes`, default true).
- `assist_prompt / start_assist`, `fix_prompt`: the Harness sessions ("Answer me in French." when the UI is fr).
- `maxxing update` sets edits under `web/` aside (`git stash push -u -- web/`) instead of failing.
- Customization checks: commit trailer `Check:` (save `--check`), overridden by `<workspace>/customizations/checks.json`
  (`maxxing custom check`).

## maxxing.license  (owner: core)
The optional Enterprise key: `activate(key)`, `release()`, `remove_key()`, `status()` (`has_key`, `key_hint` = `HM-…` + the last 4 characters, never
the key) talk to `{API}/v1/activate|release` (activation token kept as `license_seat`, only to free the seat;
machine = sha256("harness-maxxing:" + /etc/machine-id)). Also `API`, `USER_AGENT`, `disk_version()` (used by
`register.py`, `feedback.py`).
Installs from before 2.0.0a87 (`enabled()` = `license_token` in secrets.json) run the code of a signed archive
imported by their old code as a commit on `refs/remotes/origin/<branch>`. `move_to_git()` makes them a clone of
`GIT_URL` on `stable` (the `stable` commit with the same tree, else the same `__version__`; customizations
rebased; `license_token` -> `license_seat`). Triggers: `api/system._after_update` at every start (after
`MAXXING_MOVE_QUIET_S`, never while `maxxing-update` runs), the hourly loop (`move_due`, every 6 h after a
failure) and `cmd_update` (saves uncommitted non-`web/` changes first, then stops with the reason if the move
fails). Until then `_fetch` / `check_update` / `_refresh_remote` fetch nothing. Downloading and verifying archives
is gone (2.0.0a93): the old code that still runs on those servers does it.

## CLI
`maxxing.cli.register(name, help, configure(parser), handler(args) -> int)`, called from
`maxxing/cmd_core.py` (init, doctor, update, status, harden, uninstall), `cmd_cron.py` (cron run/sync/list),
`cmd_backup.py` (backup run/restore/status), `cmd_telegram.py` (telegram status/test),
`cmd_sessions.py` (sessions compact-logs), `cmd_memory.py` (memory), `cmd_import.py` (import), `cmd_video.py` (video new/status), `cmd_voice.py` (voice status/set/download/transcribe),
`cmd_custom.py` (custom status/save/drop/export/restore), `cmd_license.py` (license activate/status/remove/release).
Startup speed: `configure(parser)` runs only for the command being run (the first non-option argument),
and the `cmd_*` modules import their domain module (crons, feed, license, urllib...) inside the handler,
never FastAPI (`maxxing.security` / `maxxing.app`): `maxxing --help` ~85 ms. Keep new commands that way.
cmd_core also exposes `copy_templates(ws)` (renders `{{CODE_DIR}}`/`{{WORKSPACE}}`/`{{STATE_DIR}}`/`{{VERSION}}`, seeds each
default project/topic once - install.json `seeded`), `install_skills()` (copies `skills/*` to `<claude_dir>/skills`
and renders the same placeholders in their `.md`/`.json`/`.txt` files, so shipped skills never hard-code
`/opt/claude-maxxing`, `/root/maxxing` or `/var/lib/claude-maxxing`; `skills_status()` compares with the rendered
text), `default_jobs()` / `ensure_default_crons()` (install.json
`default_crons`), `check_update(branch) -> {ok, current, latest, behind, available, changelog}` (no change to the
code; `update_source()` = "license" | "git" (clone with an `origin` remote) | None - None: `{ok: true, git: false,
message: "no license, no remote"}`, `update --check` exits 0 with "updates unavailable (no license, no remote)", and
`default_jobs()` creates "Check for updates" disabled). "Memory compaction" is created disabled; its id goes into
install.json `enable_after_onboarding`; `enable_pending_jobs()` (called by POST /api/onboarding/complete when
`claude_auth.status().ok`) enables each listed job still disabled and never edited (`created == updated`), then
clears the list - jobs of existing installs are never touched (their key is already in `default_crons`), `notify_update(info)` (gateway.notify_cron), `version_key(v)`, `upgrade_notes(old, new)` (docs/upgrade).

## Service sandboxing (`maxxing harden`)
- `cmd_core.HARDENING` = drop-in `/etc/systemd/system/claude-maxxing.service.d/10-hardening.conf`
  (`hardening_path()` derives it from `UNIT_PATH`); install.sh writes the byte-identical text (a test checks it).
  Options: NoNewPrivileges, ProtectKernelTunables/Modules/Logs, ProtectControlGroups, RestrictSUIDSGID,
  RestrictRealtime, LockPersonality, SystemCallArchitectures=native, TasksMax=2048.
- Deliberately absent: ProtectSystem/ProtectHome/PrivateTmp (workspace, /etc/caddy and shared /tmp writes),
  RestrictNamespaces (Claude Code sandbox), MemoryDenyWriteExecute (Node JIT), UMask=0077 (files written for
  Caddy or other web servers must stay readable). Turns, updates and restarts go through `systemd-run`: PID 1
  creates those units outside this sandbox.
- `maxxing harden`: write -> daemon-reload -> restart -> `_healthy(version)`; on failure the previous drop-in
  (or none) is restored, reloaded and restarted (exit 1). `--undo` removes it. Doctor check `hardening`
  (INFO when missing or different, OK when identical). `maxxing uninstall` removes the drop-in.
- `systemd-analyze security --offline=true` on the generated unit: 9.4 UNSAFE without, 7.8 EXPOSED with
  (the rest is the root user and its capabilities, which the product needs).

## Signed updates (`update_verify_signature`)
- Config `update_verify_signature` (default false). `cmd_update`, right after the fetch and before anything
  changes (auto-save of dirty files, pre-update ref, merge/rebase): `verify_target(origin/<branch>)` =
  `git verify-commit <sha>`, else `git verify-tag` of each `git tag --points-at <sha>`; failure -> FAIL line,
  `_notify`, exit 1. Skipped when already up to date and on licensed installs (archive verified with ed25519).
  `--resume` / `--rollback` do not re-check (the target was checked when the update started).
- Doctor `update_signature` (only when on): verifies `origin/<current branch>` (else HEAD), WARN if unsigned.

## External components (deps.toml, deps.py)
- `server/maxxing/deps.toml` is the one list of what Harness Maxxing installs besides apt packages: version, URL
  template, sha256 per machine (`x86_64`, `aarch64`), path, links in `/usr/local/bin`, what `remove` deletes, update
  policy (`auto` = moved by every `maxxing update`; `self` = Claude Code; `apt`; `manual` = Garage, whose pins stay in
  `infra/actions.py`), the OSV package for `deps check`, lockfiles. Both `deps.py` (tomllib) and install.sh (`dep`, a
  regex reader: keep the syntax to `[name]`, `k = "s"`, `k = ["a"]`, one-line `k = { a = "b" }`) read it;
  `tests/test_install_reliability.py` checks they agree.
- Every download: `fetch_verified` (install.sh, bash) / `deps.fetch_verified` (server) = HTTPS, into a private work
  folder (`$WORK`, `<state>/tmp/deps.*`), sha256 checked before use. Never `curl | sh`, never a script fetched at
  install time (`tests/test_deps.py::test_no_download_is_piped_into_a_shell_anywhere`). Children get `TMPDIR` in the
  work / state folder.
- Updates are side by side: Node.js and Scrapling in `<component>/<version>` + `current` link, Remotion in
  `remotion.new` swapped with `os.replace`, uv / binaries replaced atomically; the old copy stays until the new one
  answers its check. `deps.json` records the sha256 of the installed binaries for `verify`.
- Adding a component: a table in deps.toml, an `_up_<name>` updater in `deps.py` (`_UPDATERS`, `UPDATE_ORDER`),
  `installed()` / `owned_paths()` cases, a test; bump with `scripts/bump-pins.sh` (it rewrites deps.toml in place
  and re-resolves `templates/scrapling/requirements.txt` with `uv pip compile --universal --generate-hashes`).
- One Chromium: Playwright's build in `<state>/tools/browsers` (revision of the drivers of the Scrapling lock) serves
  Scrapling, Remotion (`templates/remotion/remotion.config.js`) and `maxxing pdf` (`cmd_video.browser()`).

## Turn units (sessions/spawn.py)
`_start_unit(sid)` runs `systemd-run --collect --unit maxxing-<sid8>` (the name users pass to `journalctl -u`).
Turn and cron units get `memory_properties()`: `OOMPolicy=continue` (an OOM kill takes one process, not the
unit and its Claude) and `MemoryMax=<unit_memory_max>` (config, default 75 % of RAM).
Turn and job units also get `hardening_properties()` (see "Unit hardening" below).
When the previous runner unit of the session is still stopping ("already loaded / exists"), it polls
`systemctl show` every 50 ms (`UNIT_POLL_S`) until the unit is unloaded or inactive, at most 3 s
(`UNIT_GONE_WAIT_S`), and starts again; a unit still there after that gets `maxxing-<sid8>-<n>`.

## Unit hardening (sessions/spawn.py `UNIT_HARDENING`)
Sessions and jobs run as root with full rights on purpose (Claude administers the server: apt, systemctl, caddy,
crontab, sudo, docker/lxc CLIs, mounts); running them as another user is a separate project. Turn units and job
units get only the systemd options measured harmless for that work (transient units on systemd 259, probe of
sudo, setuid helpers, apt simulation, dpkg setuid files, modprobe, dmesg, block devices, loop/fuse/tun, sysctl
writes, mounts seen by the host, nested systemd-run, snap/lxc, Node, Chromium, ffmpeg, Python multiprocessing,
git, `claude --version`). Config `unit_hardening` (default true; false = none).

| Option | Kept? | Why |
|---|---|---|
| `ProtectClock=yes` | kept | blocks setting the clock (`date -s`, `hwclock -w`, adjtimex); `timedatectl` goes through timedated (another unit) and still works; the implied `DeviceAllow=char-rtc r` leaves the other devices open (block devices, loop, fuse, tun checked); no mount namespace |
| `LockPersonality=yes` | kept | only `personality()` changes (`setarch linux32`) fail; 32-bit binaries still run (the kernel sets their personality at exec) |
| `RestrictRealtime=yes` | kept | only realtime scheduling (`chrt -f`) fails; nothing a session runs needs it |
| `MemoryMax`, `OOMPolicy=continue` | kept | `memory_properties()` (already there) |
| `NoNewPrivileges=yes` | rejected | breaks sudo, setuid helpers (ping, fusermount, ssh-keysign) and snap (`snap-confine` is setuid). Not implied by the kept options: the units keep CAP_SYS_ADMIN (checked `NoNewPrivs: 0`) |
| `ProtectKernelTunables=yes` | rejected | /proc/sys and /sys read-only: `sysctl -w`, `sysctl --system`, ufw reloads (it writes /proc/sys/net) fail |
| `ProtectKernelModules=yes` | rejected | makes /lib/modules inaccessible: `modprobe` fails and an `apt upgrade` installing a kernel cannot write its modules |
| `ProtectKernelLogs=yes` | rejected | `dmesg` fails (the usual look for OOM kills) |
| `ProtectControlGroups=yes` | rejected | gives the unit its own mount namespace: a disk, sshfs or loop image mounted by a session is invisible to the host and gone with the turn |
| `RestrictSUIDSGID=yes` | rejected | `chmod u+s` / `g+s` fail: dpkg cannot install packages shipping setuid files (sudo, passwd, fuse3...), no setgid shared folders |
| `SystemCallArchitectures=native` | rejected | 32-bit programs (steamcmd, wine) stop working |
| `ProtectSystem`, `ProtectHome`, `PrivateTmp`, `PrivateDevices`, `ProtectProc`, `RestrictNamespaces`, `MemoryDenyWriteExecute` | rejected | writes everywhere, /tmp shared with the server, devices, `ps`, Claude Code's own sandbox (namespaces), Node JIT |

The server service keeps its own drop-in (`HARDENING`, `maxxing harden`), stricter because the server itself never
administers the host; units started with systemd-run are created by PID 1 and do not inherit it.

## Claude tuning variables (production)

`sessions/spawn.TUNING_ENV` - `CLAUDE_CODE_EFFORT_LEVEL`, `MAX_THINKING_TOKENS`,
`CLAUDE_CODE_PROMPT_CACHE_TTL`, `CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL`, `FORCE_PROMPT_CACHING_5M`,
`ENABLE_PROMPT_CACHING_1H`, `DISABLE_PROMPT_CACHING`, `ENABLE_TOOL_SEARCH`,
`CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS` (names checked in the Claude Code binary) - set on the
`claude-maxxing` service, reach every turn runner in direct and systemd modes (as `--setenv`, so
visible in `ps`: never add a secret to this list; credentials go through `auth_env()` inside the
runner). Simplest for users: the `env` block of `~/.claude/settings.json`, read by Claude Code itself.
To set them on the service: `systemctl edit claude-maxxing` -> `[Service]` `Environment=NAME=value`.

## Environment overrides (tests / development - never needed in production)
- `MAXXING_WEB_DIST` serve the UI from another build folder (dev)
- `MAXXING_STATE` state dir · `MAXXING_CLAUDE_BIN` claude executable (tests: server/tests/fake_claude.py)
- `MAXXING_PC_BIN_DIR` folder of Harness PC agent binaries (tests, local builds of `pc-agent/`) instead of the release
- `MAXXING_SPAWN=direct` run turns as detached subprocesses instead of systemd-run units
- `MAXXING_CRONTAB_FILE` write the managed crontab block into this file instead of `crontab -`
- `MAXXING_SYSTEM_TZ=0` never switch the system time zone when the time zone setting changes (also skipped when `MAXXING_CRONTAB_FILE` is set)
- `MAXXING_TELEGRAM_API` Telegram API base URL (tests: local mock) · `MAXXING_GITHUB_API` GitHub API base URL
- `MAXXING_LICENSE_API` license server (default `https://api.harness-maxxing.com`) · `MAXXING_GIT_URL` repository an install still on archives moves to (tests) · `MAXXING_LICENSE_PING=0` no hourly loop: no registration heartbeat, no call to the cloud (tests)
- `MAXXING_AUTH_CHECK=0` no background Claude sign-in verification (tests) · `MAXXING_AUTH_CHECK_DELAY` seconds
  before the first one (default 5)
- `MAXXING_CLAUDE_UPDATE=0` no background Claude Code update (tests), `=1` also on a non-default state dir · `MAXXING_CLAUDE_UPDATE_DELAY` seconds before
  the first pass (default 600)
- `MAXXING_GROQ_API` / `MAXXING_OPENAI_API` base URLs of the speech-to-text APIs (default the providers' `/v1`)
- `MAXXING_TELEGRAM_POLL` long-polling timeout in seconds (default 50) · `MAXXING_GITHUB_GIT` git base URL of the
  backup remote (default https://github.com; tests: `file:///tmp/...` with bare repos `<owner>/<name>.git`)

## Trash, import, tools (2.0.0a5)
- `maxxing/trash.py`: `list_items()`, `restore(id)`, `delete(id)`, `empty()`, `purge_old(days=30)`,
  `trash_session(sid)` (used by `sessions.service.delete_session`). Items = entries of
  `state_dir("trash")` with a `.json` sidecar `{original, at, kind?, title?, path?}` (+ `.sessions/`
  for a project / topic); `workspace.move_to_trash` writes them. API `/api/trash`. `list_items` reuses the
  last listing while the (name, inode, mtime, size) of every trash entry is unchanged (one `scandir`), keeps
  each item's size keyed by the same stat of the item and its `.sessions/` (walked again only when one
  changed), hides expired items and runs `purge_old` at most once per `PURGE_EVERY_S` (1 h);
  `invalidate_sizes()` after writing deep inside an existing item (backup restore's previous versions).
- `maxxing/importer.py`: `prompt(agent)`, `inspect(zip)` (preview, writes nothing), `apply(zip)`,
  `finish_prompt(result)`; uploads in `state_dir("import")` (24 h). Never overwrites; secret scan =
  `backup.scan_bytes`. API `/api/import`, CLI `maxxing import`.
- `maxxing/videos.py`: lighter copies for the player. `probe(p)` (ffprobe, cached by `sha1(path, mtime_ns,
  size)`), `status(p)`, `prepare(p, q)` -> `_encode` on a 1-worker pool (`nice -n 10 ffmpeg ... -progress pipe:1`,
  writes `<key>.part.mp4` then renames; `_jobs[key]` = state/progress/error in memory, lost on restart: a
  half-made copy is simply made again), `_trim_cache()` (atime LRU, `VIDEO_CACHE_MAX` 4 GB; also removes
  `*.part.mp4` older than `PART_STALE_S` whose job is not running). API in `api/files.py`.
- `maxxing/cmd_video.py`: Remotion prepared once in `<state>/tools/remotion` by `install.sh`
  (`install_tools`, `--tools`); `new_project(dir)` copies `templates/remotion` and links
  `node_modules`; `pdf(src, out)` runs `maxxing/assets/print_pdf.mjs` (DevTools `Page.printToPDF`
  through Remotion's headless shell, which has no `--print-to-pdf`). Doctor: `check_tools` (warn).

## Settings files and git credentials
- `config._atomic_write`: `mkstemp` in the same folder, permissions set before writing (`mode`, else the
  existing file's, else `0666 & ~umask`), `os.replace`. `config.json` / `secrets.json` that do not
  parse are read as `{}` (defaults) and copied to `<name>.damaged-<stamp>` before any save
  (`_keep_damaged`, `damaged_copy_of`; doctor `state_files`).
- `cmd_core.git_auth_env(token)`: the update token reaches git through `GIT_CONFIG_COUNT/KEY_0/VALUE_0`
  (`http.extraHeader`), never through `-c` arguments; used by `cmd_core._git` and `api/system._git`.

