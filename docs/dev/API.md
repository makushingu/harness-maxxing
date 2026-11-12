# API contract (v2.0)

Single source of truth between `server/` and `web/`. Change it here first, then on both sides.

## Conventions
- Base path `/api`. JSON in and out (`Content-Type: application/json`) unless stated.
- Auth: signed cookie `mx_session` (HttpOnly, SameSite=Strict, `Secure` when the request came over HTTPS
  i.e. `X-Forwarded-Proto: https`). Unauthenticated → `401 {"error":"auth_required"}`.
- CSRF: every non-GET request must carry header `X-Maxxing: 1`, else `403 {"error":"csrf"}`.
- Multipart requests (uploads, import, voice): the cookie and the CSRF header are checked **before** the body is
  read (`401` / `403`). Then `413 too_large` if `Content-Length` (or the streamed body) exceeds config
  `upload_max_mb` (default 2048; 0 = no cap; + 1 MB of multipart framing), and `507 disk_full` if the body does not fit
  in the spool dir (`<state>/tmp/uploads`, where the server spools uploads) with min(`upload_min_free_mb`, 128 MB)
  to spare. The full `upload_min_free_mb` reserve (default 1024) is checked on the destination disk per file.
  Both keys are read from config.json on every request (no restart).
- Other request bodies (JSON, forms...) are capped before they are read (`maxxing/bodylimit.py`), on the declared
  `Content-Length` and, for a chunked body, while it streams: without a valid cookie a mutating request to a route
  that needs one gets `401 auth_required` before a byte is read; the public `/api/auth/*` routes check the CSRF header
  first (`403 csrf`) and take at most 64 kB, `/api/hooks/{token}` 1 MB. Signed in: 1 MB by default; 16 MB for
  `PUT /api/files/write` (the editor opens text up to 2 MB, JSON escaping can grow it), 8 MB for the session routes
  that carry a prompt (`POST /api/sessions`, `/messages`, `/steer`, `/ask`), 5 MB for `/api/ext/*`. Over it:
  `413 {"error":"too_large"}` (`Connection: close`).
- Errors: `{"error": "<machine_code>", "message": "<human text>"}` with a 4xx/5xx status.
- Compression: JSON responses >= 1 kB are gzipped (`Content-Encoding: gzip`, `Vary: Accept-Encoding`) when the
  client accepts gzip and the request did not come through a proxy (no `X-Forwarded-For`; Caddy's `encode` does it
  in domain mode). SSE streams and file downloads are never compressed by the server.
- Timestamps: Unix seconds (float) named `at`, `created`, `updated`.
- Paths:
  - *topic path* = path relative to the workspace root, e.g. `projects/acme/topics/blog`
    (`""` = workspace root).
  - *file path* = absolute path, must be inside `files_root`.
- IDs: sessions = UUID4; tasks/crons/projects = short random ids (`t_…`, `c_…`).

## Auth & setup
| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/auth/state` | – | `{setup_required, authenticated, version, onboarding_completed, language, look:{theme:"dark"\|"light"\|"system", accent, tint:"neutral"\|"tinted"}\|null}` (public; `look` = the last one chosen in a signed-in browser, shown by the sign-in page and by browsers that never chose one) |
| POST | `/api/auth/setup` | `{token, password}` | `200 {ok}` + cookie. Only while `setup_required`; token = one-time setup token. `403 bad_token` |
| POST | `/api/auth/login` | `{password}` | `200 {ok:true}` + cookie, or with two-step sign-in on and no trusted-browser cookie `200 {ok:false, two_factor:{challenge, expires_in}}` (no cookie; `429 throttled` past 5 requests / 15 min per client or 10 pending; `503 two_factor_unavailable` when Telegram refused the message) · `401 bad_password` (after a delay) · `429 throttled` (checked before the password: 8 failures / 15 min per client, or the global cap - 30 failures from all clients - then one check per 5 s) |
| POST | `/api/auth/two-factor` | `{challenge, code?, trust?:bool(true)}` | poll: `{ok:false, status:"pending", expires_in}` · `{ok:true, status:"approved"}` + session cookie (+ `mx_device` cookie, path `/api/auth`, 30 days, when `trust`) - once only · `400 bad_code` `{tries_left}` (also a code that is not 6 ASCII digits) · `429 codes_paused` (20 wrong codes server-wide in the last hour: only Allow works) · `403 denied` · `410 expired` (also after 5 wrong codes, after TTL + 60 s even once approved, and after a password change / 2FA off / forget-browsers). A challenge of `PUT /two-factor` needs the session cookie and turns two-step sign-in on instead |
| PUT | `/api/auth/two-factor` | `{enabled, password?}` | auth. `false`: needs the current `password` when on (`401 bad_password`, `429 throttled`, own counter like `/password`), then off (trusted browsers forgotten, notice in Telegram + feed) → `{ok, enabled:false}`. `true`: `409 not_linked` without a Telegram chat; already on → `{ok, enabled:true}`; else `{ok:false, two_factor:{challenge, expires_in}}`, on only once approved (poll `POST /two-factor`), this browser becomes trusted |
| POST | `/api/auth/two-factor/forget-browsers` | – | auth. New `device_key`: every trusted browser asks again, this one is re-trusted → `{ok}` |
| POST | `/api/auth/logout` | – | `{ok}` + cookie cleared. The cookie is also revoked server-side (`secrets.revoked_sessions`, kept until it would have expired): a copy of it is refused afterwards; other browsers stay signed in |
| POST | `/api/auth/password` | `{current, new}` | `{ok}` (min length 12, `security.MIN_PASSWORD`; `400 weak_password`, `400 invalid_password` for a character UTF-8 cannot store, same on setup) + new cookie · wrong `current`: `401` after the sign-in delay, `429 throttled` past `FAIL_MAX` (own counter `pw:<client>`); rotates the cookie key: every other browser is signed out |

## Onboarding
| GET | `/api/onboarding` | – | `{completed, steps:{password:bool, claude:bool, workspace:bool, telegram:bool, backup:bool, profile:bool}}` (`profile` = the Profile step was answered, `register.asked`) |
| POST | `/api/onboarding/complete` | – | `{ok, jobs_enabled:[cron_id]}` (Claude signed in: the default jobs created off until then - Memory compaction - are turned on, once) |

## Claude
| GET | `/api/claude/status` | – | `{installed, version, auth:{ok, method:"oauth_token"\|"credentials"\|"api_key"\|null, detail, checked_at:float\|null, error:string\|null}, default_model, permission_mode, auto_compact_tokens, idle_compact_tokens, idle_compact_after_s, smart_resume_tokens, protect_secrets:bool, short_titles:bool, short_titles_model:bool, auto_update:{enabled:bool, checked_at:float\|null, latest:string\|null, last:{from, to, at:float, ok:bool, error:string\|null}\|null}, models:[{id,label,context_window:int\|null}]}` (`context_window`: as last reported by Claude Code on this server, null if never seen) |
| POST | `/api/claude/auth` | `{kind:"oauth_token"\|"api_key", value}` | stores the secret then runs a test call → `{ok, error?}`; 400 `invalid` if `value` is shorter than 10 characters or not printable ASCII without spaces |
| DELETE | `/api/claude/auth` | – | removes stored token/key |
| POST | `/api/claude/test` | – | `{ok, model, ms, error?}` (real one-line call) |
| PUT | `/api/claude/settings` | `{default_model?, permission_mode?, auto_compact_tokens?, idle_compact_tokens?, idle_compact_after_s?, smart_resume_tokens?, protect_secrets?, short_titles?, short_titles_model?, claude_auto_update?}` | `{ok}` · default_model: empty, or a model id (1-100 of `A-Za-z0-9._:[]/@-`), else 400 `invalid` · protect_secrets: deny rules on secrets.json and ~/.ssh for every turn · short_titles (default true): a session created with a message and no title gets a short title in the background, made locally, or by the smallest model with short_titles_model (default false) (INTERNALS.md `maxxing.sessions.titles`) · claude_auto_update (default false): the server runs `claude update` while idle, only for a release out for 2 days (INTERNALS.md#maxxingclaude_update) · permission_mode ∈ `bypass` (default) \| `acceptEdits` \| `default` · auto_compact_tokens: 0 = off, else a turn ending above it (at least 100 000) queues a summary turn + fresh thread (default 300 000) · idle_compact_tokens (0..2 000 000, default 200 000; 0 = off, else at least 20 000) / idle_compact_after_s (300..604 800, default 3600): a user message to a session idle for longer, with at least that context, is preceded by a summary turn and runs in the fresh thread · smart_resume_tokens (0..2 000 000, default 60 000; 0 = off, else at least 20 000): a user message after a pause of 5 min+ to a session with at least that context (cache expired, or 100 000+) is sorted by a small model call: NEW -> summary turn first, CONTINUE -> no summary, failure -> the idle rule |

`auth` reflects REAL calls, not the presence of a credentials file: the last session turn or test call with the
current method (success → `ok`, `checked_at`; a sign-in error such as "OAuth session expired…" or "Invalid API
key" → `ok:false`, `error`). A new `claude /login` (credentials file rewritten) or a new token clears an old
failure. With no recent result the server verifies in the background (`claude -p`, cheapest model, 60 s timeout)
at startup and at most every 6 h; a background timeout/network error does not mark the sign-in as failed.
`checked_at:null` = configured but not verified yet.

`models` = the newest model of each family read from Anthropic once a day (`claude_models`; before the first read claude-opus-5-5, claude-sonnet-5-5, claude-haiku-5-5, claude-fable-5-1) + ids observed in logs.

## Workspace
| GET | `/api/workspace/tree` | – | `{root, projects:[Project]}` |
| POST | `/api/workspace/projects` | `{name, description?}` | `Project` (creates folder, CLAUDE.md, memory.md; a description that is not valid UTF-8 → `400 bad_description`, nothing created; same check on topics and PATCH) |
| PATCH | `/api/workspace/projects/{project}` | `{name?, description?, emoji?}` | `Project` (rename moves the folder and remaps sessions; `emoji` = one emoji, `""` removes it, else `400 bad_emoji`; stored in `projects/<p>/.maxxing.json`) |
| PUT | `/api/workspace/order` | `{names: [project]}` | `{projects}` (tree order, stored in `projects/.order.json`; unlisted projects follow A-Z) |
| PUT | `/api/workspace/projects/{project}/order` | `{names: [topic]}` | `{topics}` (stored in `projects/<p>/.maxxing.json`) · `404` |
| DELETE | `/api/workspace/projects/{project}` | – | moves to trash · `409 has_running_sessions` |
| POST | `/api/workspace/projects/{project}/topics` | `{name, description?}` | `Topic` |
| PATCH / DELETE | `/api/workspace/projects/{project}/topics/{topic}` | `{name?, description?, permission_mode?}` | `Topic` · `permission_mode` ∈ `bypass` \| `acceptEdits` \| `default` \| `""` (the global setting), else `400 bad_permission_mode`; stored in `topics/<t>/.maxxing.json` |

```
Project = {name, path, description, topics:[Topic], session_count}
Topic   = {name, project, path, description, permission_mode:""|"bypass"|"acceptEdits"|"default", session_count, archived_count:int, running:int, unread:int, telegram_thread:int|null, agents:[Agent]}
```
`Topic.agents` = the agents of the topic (`[]` when none, see [Agents](#agents)); a session `path` may be an agent path
`projects/<p>/topics/<t>/agents/<a>` (3rd level: same rules as a topic path).
Names: `^[a-z0-9][a-z0-9-]{0,47}$` (slug); the UI slugifies the label. Description goes into the CLAUDE.md header.

## Sessions
```
Session = {
  id, title, path,                    // topic path
  state: "idle"|"running"|"error",
  queue: int,                         // messages waiting
  queue_items: [{text, attachments: int, source: "web"|"telegram"|"cron"|"system", kind, voice?:true}],  // the waiting messages, in order (text cut at 280 chars): the queue stack shows them even when this tab did not queue them
  sent_items: [{text, attachments: [path], source, voice?:[path], client_ids?}],  // sent but not in the log yet (held at the head while a summary runs first, or its turn starting; text cut at 4000 chars): the thread shows them as sent, also after a reload or in another window
  created, updated, turns, cost_usd,
  model: string,                      // chosen ("" = default)
  real_model: string|null,            // model that actually answered last turn (from the log)
  context_tokens: int|null,           // last turn input+cache tokens
  context_window: int|null,           // context window of the model of the last turn (Claude Code `modelUsage[..].contextWindow`, e.g. 1000000); null = unknown
  archived: bool, favorite: bool, notify: bool,
  source: "web"|"telegram"|"cron",
  cron: bool,                         // started by a scheduled job (not mirrored on Telegram)
  unread: bool,                       // finished after the last /seen
  last_text: string,                  // first 200 chars of the last assistant text
  error: string|null,
  plan_mode: bool,                    // turns run read-only (`--permission-mode plan`) and end with a plan
  permission_mode: string,            // set by its cron ("" = the topic's, else the global mode)
  plan_ready: bool,                   // a plan-mode turn finished OK: its plan waits for POST /plan/approve
  approvals: int                      // tool calls waiting for the user's Allow / Deny (agent with `approvals`)
}
```
| GET | `/api/sessions?path=&archived=0\|1` | – | `[Session]` sorted by `updated` desc (no path = all) |
| POST | `/api/sessions` | `{path, message?, title?, model?, attachments?:[filepath], plan_mode?:bool, voice?:filepath, client_id?}` (`client_id`: as for `/messages`, for the first message) | `Session` (starts the first turn if message or voice) |
| GET | `/api/sessions/{id}` | – | `Session` |
| PATCH | `/api/sessions/{id}` | `{title?, model?, archived?, notify?, plan_mode?, favorite?, path?}` | `Session` (`plan_mode:false` also clears `plan_ready`; `favorite` is carried over by a hand-off; `path` moves the session to another topic and its Claude transcript with it - `400 bad_path`, `409 busy` while a turn runs or messages wait; `model`: an id of letters, digits and `._:@/[]-`, 100 characters at most, not starting with `-`, else `400 bad_model`, also on create) |
| POST | `/api/sessions/{id}/plan/approve` | `{text?}` (shown in the thread as the user's message) | `{queued:bool, session:Session}` — plan mode off, then a turn that tells Claude to implement its latest plan (queue item flag `plan_approved`, kept by steer like `hud`) |
| DELETE | `/api/sessions/{id}` | – | `{ok}` (stops a running turn, moves the session to the trash) |
| POST | `/api/sessions/{id}/messages` | `{text, attachments?:[filepath], hud?:bool, voice?:filepath, client_id?}` (`client_id`: the sender's own id for the message, `[A-Za-z0-9_-]{1,64}`, kept in `client_ids` of its queue item (`queue_items`) and of its `user` event, so a page reloaded mid-send can tell whether it arrived; `hud`: sent from the HUD - the prompt gets a short preface: answer short, annotate the screen capture if useful; `voice`: a voice message sent directly - uploaded first with `/api/uploads`, queued at once, transcribed by the server, then its transcript is the prompt) | `{queued:bool, session:Session}` · `409 voice_off` (transcription not ready) |
| DELETE | `/api/sessions/{id}/queue` | – | clears queued messages |
| POST | `/api/sessions/{id}/ask` | `{question}` | `{answer, cost_usd, duration_ms}` — side question: Claude answers from a throwaway copy of the session's thread (read-only, nothing saved: the running turn, queue and log are untouched). 409 `no_thread` (never answered yet) / `busy` (one already running for this session), 429 (2 running), 504 (240 s) |
| POST | `/api/sessions/{id}/queue/take` | – | `{messages:[{text, attachments}], session}` — removes the queued user messages and returns them (the composer's **Edit**: they come back in the composer and are sent again as a normal message) |
| POST | `/api/sessions/{id}/hide` | `{at, hidden=true}` | `{ok}` — hides (or shows again) the user message whose `at` is given: appends `{type:"mx_hide", ref, hidden}` to the raw log (nothing is erased; Claude's own thread is untouched), streamed as a `hide` event; 404 when no user message has that `at`, nothing written when it is already in that state. The UI offers it for a message whose turn ended without any answer (stopped) and drops that turn's rows |
| POST | `/api/sessions/{id}/inject` | – | `{injected:bool, reason, session}` — **Add now**, without interrupting: the queued user messages become ONE message written into the running turn (SIGUSR2: the runner writes it to Claude's stream-json stdin), read by Claude at its next step, between two tool calls. When the runner cannot write it (the turn just ended), the message stays queued and runs after the turn - never lost, never sent twice. `injected: false` with `reason`: `idle` (no turn running / nothing queued), `unsupported` (a runner from before this route), `summary` (a compact / hand-off summary runs), `voice` / `plan` (voice messages and plan approvals run as their own turn: steer or wait) |
| POST | `/api/sessions/{id}/steer` | – | `{steered:bool, interrupted:bool, session}` — while a turn runs: the queued user messages become ONE message (`steer: true`) at the head of the queue and the runner gets SIGUSR1: it ends the current turn (only that one: meta `steer_turn` = `turn_id`) and runs that message next in the same Claude thread, prefaced so Claude continues the task with it. A compact / handoff turn is not interrupted (`interrupted:false`, the message runs right after it). `steered:false` when idle or nothing is queued |
| POST | `/api/sessions/{id}/stop` | – | `{ok}` (clears the queue, aborts the running turn; returns once settled, ≤ ~10 s). During an idle-compaction summary only the summary is aborted: the message waiting behind it (queue item `held`) stays and runs |
| POST | `/api/sessions/{id}/compact` | – | `{ok}` summary → fresh Claude context, same session · `409 busy` while running · `400 empty_session` |
| POST | `/api/sessions/{id}/handoff` | – | `Session` (new session seeded with a summary; old one archived). Messages sent to the new session before the summary arrives are queued (`queued:true`) and run after the seed (10 min at most, or at once when the summary fails) |
| POST | `/api/sessions/{id}/seen` | – | `{ok}` |
| GET | `/api/sessions/{id}/events?tail=N` | – | last events, read backwards from the end (whole log lines, at least N events when available, max 5000): `{events, start, next, more_before:bool, state}` — `start` = offset of the first line returned, `next` = end offset (start the stream there). What the UI uses to open a thread |
| GET | `/api/sessions/{id}/events?before=<offset>&limit=N` | – | events strictly before `offset` (backward paging, "Show earlier messages"): `{events, start, next:offset, more_before, state}` · `{events:[], reset:true, state}` when `offset` is not a line boundary of the current log |
| GET | `/api/sessions/{id}/events?from=0` | – | forward reading `{events:[Event], next:int, state, more:bool}` (≤ 4 MB of log per call; `more` = call again from `next`) · `reset:true` when `from` is beyond the end / not a line boundary |
| GET | `/api/sessions/{id}/stream?from=0` | – | **SSE**. `event: events` `data: {events, next}` · `event: state` `data: Session` · `event: reset` `data: {}` then end of stream when the log was rewritten or shrank (or `from` is stale): reload with `?tail=` · heartbeat comment every 15 s. New lines and state changes are pushed ~0.05-0.15 s after they are written (inotify on the sessions folder; without it the stream polls every 0.1 s while the session runs) |
| GET | `/api/sessions/search?q=` | – | `[{id, title, path, snippet, at}]` (served by the full-text index, see Search; max 50) |
| POST | `/api/uploads?path=<topic path>` | multipart `file` (multi) | `{files:[{path, name, size, mime}]}` saved in `<topic>/attachments/YYYY-MM/` · each file `413 too_large` over `upload_max_mb`, `507 disk_full` when it would leave less than `upload_min_free_mb` free on the destination disk (all or nothing: the files saved before it in the same request are removed); the whole request, all its files together, is capped too (see Conventions) |

`from`/`next`/`start`/`before` = byte offsets in the raw log (always line boundaries). Backward reads scan at
most 64 MB per call (then `more_before` with the `start` reached; a single line longer than that is skipped). A `task` whose `task_started` line is before the
page gets that line's `kind`/`background`/`description`/`agent_type` on its first event of the page (looked up at
most 32 MB further back, found or not remembered per log file). The runner clips tool outputs before
writing them (2 000 characters per tool result, images → `[image]`, Write/Edit inputs beyond 20 kB; the block
gets `mx_clipped`), keeps only `cwd, session_id, model, permissionMode, apiKeySource, claude_code_version,
output_style, fast_mode_state, mcp_servers, uuid` of `system/init` lines (the tool / skill / slash-command
lists, ~20 kB per turn, are dropped), drops the `signature` of `thinking` blocks and the `data` of
`redacted_thinking` blocks (read by the API only) and does not write `system/thinking_tokens` lines; `maxxing sessions
compact-logs [--dry-run]` applies the same to existing logs (atomic
rewrite, running sessions skipped), and the server does it every night at 04:30 for the logs written since the
previous night — open streams then receive `reset`. **Event** (normalised):
```
{type:"user", text, attachments:[path], at, source, voice?:[path]}   // voice: a voice message sent directly (its audio)
{type:"voice_text", text, error:str|null, stopped?:true, at}   // transcript of the voice message just above (error: not transcribed, nothing sent to Claude)
{type:"assistant", text, at}                       // markdown
{type:"thinking", text, at}
{type:"tool_use", id, name, input, input_lines?, summary, at}     // summary = one-line human string ("Read src/app.py", "Bash: ls -la")
                                                    // input text fields over 20,000 chars are clipped; input_lines = {field: real line count} of the clipped top-level ones
{type:"tool_result", tool_use_id, text, is_error, at}   // text truncated to 20 kB
{type:"init", model, cwd, at}
{type:"result", ok, cost_usd, duration_ms, model, usage:{input,output,cache_read,cache_write}, at}   // cost_usd = this turn only (the raw total_cost_usd is the thread's running total)
{type:"note", text, level:"info"|"warn"|"error", at}   // compact, handoff, resume fallback, stop…
{type:"hide", ref, hidden, at}                      // ref = `at` of a user event: hidden (true) or shown again{type:"task", id, tool_use_id?, at, state?, kind?, background?, description?, agent_type?, activity?, last_tool?, tokens?, tools?, duration_ms?, summary?}
                                                    // background work of Claude Code (task_started / _progress / _updated / _notification):
                                                    // a partial update, merged on `id`; `tool_use_id` = the Agent / Bash call that started it.
                                                    // state: running|completed|failed|stopped · kind: agent|shell|other ·
                                                    // summary = the agent's final report (≤ 20 kB) · commands run by a sub-agent are dropped.
                                                    // Not counted in `tail` / `limit` (they are not thread rows).
```

## Global bus
`GET /api/stream` — **SSE**, `event: invalidate`, `data: {"topics": ["sessions"|"workspace"|"tasks"|"crons"|"telegram"|"backup"|"health"|"extensions"|"trash"|"feed"]}`. The UI refetches the matching queries. Heartbeat every 15 s. Both SSE streams (this one and `/api/sessions/{id}/stream`) re-check their cookie before each frame (one stat of secrets.json while unchanged, a full check at least every 15 s): signed out, password changed, `sessions_not_before` or expired -> the stream ends without sending anything more (the browser's reconnect then gets `401`). Concurrent SSE streams are capped (both kinds together): 24 per sign-in, 96 in total (`streamcap`); beyond that `429 {"error":"too_many_streams"}` with `Retry-After: 5`. A session that appears, goes away or changes state/unread (turn started or ended) sends `sessions` and `workspace` together; the UI relies on that pair to refresh the workspace tree, the Claude status and the token stats.

## Files
Every `path` is absolute and inside `files_root` (else `400 bad_path` / `403 forbidden`); a path with a NUL byte or a symlink loop is `400 bad_path`.
| GET | `/api/files/list?path=` | – | `{path, parent, root, entries:[{name, path, type:"file"\|"dir", size, mtime, mime}]}` dirs first |
| GET | `/api/files/read?path=` | – | `{path, content, mtime, size, mime, editable}` (text ≤ 2 MB; else `413`; binary / non-UTF-8 → `415 binary`) |
| GET | `/api/files/raw?path=&download=0&v=` | – | bytes, Range supported (video). Every type but images (not SVG), audio, video and PDF gets `Content-Security-Policy: sandbox; default-src 'none'; …` (+ `nosniff` always). `v` (the file's mtime, set by the UI when it knows it) = cached by the browser for good, else `no-cache` + ETag. `download=1`: `Content-Disposition: attachment; filename="<ASCII fallback>"; filename*=UTF-8''<name>` (`downloads.content_disposition`: a name that is not UTF-8 on disk is read as Latin-1; slashes, control and bidi characters replaced or dropped; cut at 200 characters keeping the extension) |
| GET | `/api/files/zip?path=&check=0` | – | the folder as a zip (`application/zip`, `<folder>.zip`, `no-store`), made while it is sent: ZIP64, deflate level 6, stored for already-compressed types (images, video, audio, archives, office, PDF, fonts). Everything the listing shows; symlinked folders are not followed, a symlinked file only when its target is a regular file inside the files root; sockets / FIFOs / devices left out; names not UTF-8 read as Latin-1 · not a folder `404` · over 2 GB uncompressed or 100,000 entries `413 too_large` (checked before the first byte) · `check=1`: `{count, size}` (files, uncompressed bytes) or that `413`, nothing zipped: the UI asks first, a refused link download shows no reason |
| POST | `/api/files/zip` | `{paths: [abs path]}` (1-1000) | several files and folders in one zip, checked: each path confined like every other (symlinks followed, `403` outside, `404` missing, `400` relative), duplicates and entries inside another selected folder left out, a name already taken gets ` (2)`; the 2 GB / 100,000 caps apply to the whole set (`413 too_large`) → `{count, size, name, token, expires_in}` (`name`: `<their folder>.zip`, or `files.zip` when they come from several folders) |
| GET | `/api/files/zip?token=` | – | the zip of that POST (same session cookie only, valid `expires_in` = 120 s), planned again from the paths as they are now (`413` if it grew past a cap) · unknown / expired / another session `404`. A link download cannot POST: the browser follows this URL |
| GET | `/api/files/thumb?path=&w=320&v=&anim=0` | – | webp thumbnail for images, videos and PDFs (ffmpeg, video: frame at 1 s; PDF: first page through `pdftoppm`), cached server side; without ffmpeg images fall back to the original · other types `415`. `w` ≤ 4096. `anim=1` (chat): a `.gif` of at most 8 MB (`GIF_ANIM_MAX`) is served as it is (`image/gif`, it moves), a bigger one gets the still. Cache: `no-cache` (revalidated), or for good with `v`. Same CSP rule as `/raw` (an SVG fallback is sandboxed) |
| GET | `/api/files/preview?path=&w=2048&v=` | – | the image for the viewer: a WebP at most `w` px wide (64-4096, default 2048) when the original is heavy (over 300 kB, or a format the browser cannot show: then converted), else the original (`.gif` and `.svg` always as they are; no ffmpeg: the original). `v`: as on `/raw` · `404 not_found` · `415 unsupported` (not an image, or a format this server cannot convert) |
| GET | `/api/files/archive?path=` | – | lists a zip, tar (gz/bz2/xz) or single `.gz` without extracting it: `{path, format:"zip"\|"tar"\|"gzip", entries:[{name, size, dir, mtime}], count, total_size, truncated, size}` (at most 5,000 entries, 256 MB read and 3 s: then `truncated`; cached per file version) · `404 not_found` · `415 unsupported` (another format, or unreadable) |
| POST | `/api/files/stat` | `{paths: [str]}` (≤ 500) | `{mtimes: {path: float \| null}}` - current mtime of each file (null = missing, outside the files root, not absolute; a path with a lone surrogate is left out). The UI puts it in preview URLs (`v`) so a file rewritten under the same name shows its new version |
| – | `within=<abs folder>` on `/raw`, `/preview`, `/thumb` (repeatable, ≤ 20), `within: [str]` in `/stat` | – | the automatic previews of agent answers: the file's real path (links followed) must also be in the real path of one of these folders (each itself inside the files root), and the path may hold no `.` / `..` part, else `403` (`/stat`: null). Without it, unchanged |
| GET | `/api/files/video?path=` | – | `{width, height, codec, bitrate, duration, fps, has_audio, rotation, qualities: [{q, state: none\|queued\|running\|ready\|error, progress 0-1, error?}], auto}`: `width`/`height` as coded (`rotation` 90 / 270 = shown sideways), `has_audio` false = no audio stream (the UI plays a clip of ≤ 15 s without sound like a GIF); the lighter copies offered (1080 / 720 / 480 below the original's height) and `auto`, the copy the UI falls back on when the browser cannot decode the original (it checks `canPlayType` with `codec`) or it struggles: 1080 above 1080p, 720 for a heavy original ≤ 1080p (not H.264 / VP8 / VP9, or > 6 Mbit/s), `null` = none (light original, or nothing lighter) · not a video `415` · no ffprobe / no video stream `422 video_unavailable` |
| POST | `/api/files/video/prepare` | `{path, q}` | queues the copy at height `q` (H.264 crf 20 `faster` + AAC 128k, maxrate 8M / 4M / 1.5M with a buffer twice that, `+faststart`, `nice 10`, 2 threads, one encode at a time) in `<state>/videos/<sha1(path, mtime, size)>-<q>-r2.mp4` (`r2`: copies made with older settings are never served); no-op when ready or queued; returns the same as GET · `q` not offered or no ffmpeg `422`. Poll GET for progress |
| GET | `/api/files/video/stream?path=&q=&v=` | – | the ready copy (`video/mp4`, Range requests) · not made yet `404 not_ready`. Sets the copy's access time only (its mtime, so the ETag / Last-Modified, never change: the browser's `If-Range` requests keep getting 206). Past 4 GB (`VIDEO_CACHE_MAX`) the least recently played copies are removed after each encode, never one played in the last 30 min (`COPY_KEEP_S`) |
| GET | `/api/files/site-url?path=` | – | `{url, expires_in}`: `/api/files/site/<token>/<name>` renders an HTML file (`.html`/`.htm` only, 415 otherwise) with its relative assets for 2 h. Folder token: only static web assets of the page's folder tree (`html htm css js mjs wasm`, fonts `woff woff2 ttf otf eot`, pictures, audio, video; never `.md .json .txt .csv .pdf .xml`, code or settings); from a topic's `attachments/`, pictures and media only. When the page's folder is the files root, the home directory, `/`, under a dot folder, the workspace root, `projects/`, a project, its `topics/` or a topic's `attachments/`, the token covers that file only (never under a dot folder). The token carries its issue time and session id: refused after that session signs out, when it is older than `sessions_not_before`, or after a password change |
| GET | `/api/files/site/<token>/<rel path>` | – (**no cookie**: the token, scoped to the page's folder, is the permission) | the file, with `Content-Security-Policy: sandbox allow-scripts allow-popups allow-forms allow-modals allow-downloads` (no `allow-same-origin`: opaque origin, no session; no `allow-popups-to-escape-sandbox`: popups and `target=_blank` links inherit the sandbox; the UI iframe uses the same flags) + `frame-ancestors 'self'`; outside the folder, any dotfile / dot folder in the path, another file of a single-file token, or a file type outside the list above `403`; expired, revoked / forged token `403 expired` |
| PUT | `/api/files/write` | `{path, content, expected_mtime?}` | `{ok, mtime}` · `409 conflict` when mtime differs · `400 bad_content` (a lone surrogate) |
| POST | `/api/files/mkdir` | `{path}` | `{ok}` · `409 exists` when something (a file, a dangling link) is already there or a file is in the way |
| POST | `/api/files/move` | `{from, to}` | `{ok}` · moving the workspace or a folder holding it `403 forbidden`; a folder with a running session in it `409 has_running_sessions` (same rule as the workspace API) |
| POST | `/api/files/delete` | `{path}` | `{ok}` (to trash) · same `403` / `409 has_running_sessions` rules as `move` |
| POST | `/api/files/upload?dir=` | multipart | `{files:[…]}` · same limits as `/api/uploads` (`413 too_large`, `507 disk_full`) |
| GET | `/api/files/search?q=` | – | `[{path, name, type}]` (workspace, max 50) |

## Trash
Everything deleted (files, folders, topics and projects with their sessions, single sessions) lands in
`state_dir("trash")`; items older than 30 days are hidden from the list and purged when the trash is listed (at most once an hour); `.sessions` / `.agents` folders and sidecars left without their item (a restore cut short) go with that purge and when the trash is emptied.
| GET | `/api/trash` | – | `{items:[{id, kind:"file"\|"folder"\|"topic"\|"project"\|"session"\|"previous_versions", name, original, at, size, sessions:int, restorable}], keep_days}` newest first (`original` workspace-relative; for a session: its topic path) |
| POST | `/api/trash/{id}/restore` | – | back where it was - a free name next to it if the place is taken (`<name> (restored).ext`, topics/projects `<name>-restored`, `<name>-restored-2`…, the name cut so the result stays a valid name of at most 48 characters); sessions come back with their topic (a session whose topic is gone comes back at the workspace root) → `{ok, kind, restored_to, sessions}` · `404 not_found` · `409 not_restorable` (backup "previous versions", or a recorded place outside the workspace and the files root) · `409 project_in_trash` (a topic or an agent whose project waits in the trash) · `409 topic_in_trash` (an agent whose topic waits in the trash): restore that one first · `400 bad_id` (a `/`, a leading `.`, or longer than a file name: 255 bytes) |
| DELETE | `/api/trash/{id}` | – | deletes one item forever → `{ok}` · `400 bad_id` (as for restore) · `404 not_found` |
| DELETE | `/api/trash` | – | empties the trash → `{ok, deleted}` |

## Tasks (`<workspace>/tasks.json`)
```
Task    = {id, title, notes, status:"todo"|"doing"|"done", priority:0|1|2|3, due:"YYYY-MM-DD"|null,
           project_id|null, topic_path|null, labels:[str] (max 50, 40 chars each), created, updated, done_at|null, order:float}
TaskProject = {id, name, color, workspace?: str, hidden?: true}
```
Workspace link: every workspace project has one task project with `workspace = <project folder name>`. `GET` creates the
missing ones (an unlinked project with the same name, case-insensitive, is linked instead; `system` starts `hidden`),
fills `project_id` of tasks that have a `topic_path` but no project, and frees (removes `workspace`) a project whose folder
is gone; a workspace rename moves `workspace`, `name` (when it was the old name) and the tasks' `topic_path`; a deleted
project leaves a free task project (its tasks keep it), a deleted topic clears `topic_path`. POST with a `topic_path` and no
`project_id` takes the topic's project. `DELETE` of a linked project whose folder exists: `409 linked_project` (hide it).
A hand-written file is normalised on read (missing fields filled in, `id` / `title` / `notes` / `project_id` / `topic_path` of
another type turned into text, non-numeric `created` / `updated` / `done_at` replaced). Every write (POST / PATCH / DELETE
below) is a read-modify-write under one lock; when the file changed on disk between the read and the write (Claude edited it),
the change is re-applied on the fresh file (3 tries), then `409 conflict`. Not valid JSON: every route `409 corrupt_file`.
| GET | `/api/tasks` | – | `{projects:[TaskProject], tasks:[Task]}` |
| POST | `/api/tasks` | partial Task (title required) | `Task` · `422` when `order` is not a finite number |
| PATCH | `/api/tasks/{id}` | partial Task, optional `prev_id` / `next_id` (the cards it was dropped between: placed there, the column renumbered when their orders leave no room) | `Task` · a status change without `order` puts it on top of `done`, at the bottom elsewhere · `422` when `order` is not a finite number |
| DELETE | `/api/tasks/{id}` | – | `{ok}` |
| POST | `/api/tasks/bulk` | `{ids:[id], patch?:{status?, priority?, project_id?, due?, topic_path?, labels?}, labels_add?:[str], labels_remove?:[str], delete?:bool}` | `{ok, updated, deleted}` — one atomic write; unknown ids ignored; tasks entering a column keep their relative order (top of `done`, bottom elsewhere) · `400 invalid_ids`/`too_many_ids` (more than 1000 ids)/`invalid_labels` (more than 50 labels on a task)/validation codes of PATCH |
| POST / PATCH / DELETE | `/api/tasks/projects[/{id}]` | `{name, color, hidden?}` | `TaskProject` · DELETE `409 linked_project` |

## Crons
```
Cron = {id, name, schedule,            // 5-field cron expression ("" for a one-time job)
        once_at:string, once_ts:float|null, delete_after:bool,  // one-time job: "YYYY-MM-DDTHH:MM" in the configured zone
        done_at?:float, missed?:bool,  // one-time job that ran (or was missed for good): disabled
        catch_up:bool(true), retries:int(0-5, shell only), retry_at:float|null,  // a retry waits until then
        kind:"shell"|"claude", command, // shell
        topic_path, prompt, model, reuse_session:bool,  // claude
        permission_mode:""|"bypass"|"acceptEdits"|"default",  // claude; "" = the topic's, else the global mode
        enabled, notify:"never"|"failure"|"always", timeout_s,
        last_run:{at, ok, code, duration_s, trigger, attempt, silent}|null, next_run:float|null, human:string,
        running:bool}                  // a run is in progress (flock held); overlapping runs are skipped
Run  = {id, cron_id, name, at, ok, code, duration_s, output_tail, session_id|null,
        trigger:"manual"|"schedule"|"catch-up"|"retry", attempt?:int (absent = 1), slot?:float (catch-up: the missed time),
        silent?:true (the answer was [SILENT]), retry_at?:float (failed, retried then)}
        (output_tail: a Claude job keeps the first 2048 characters of its answer, a command the last 2048 of its output)
```
| GET | `/api/crons` | – | `{jobs:[Cron], external:[{schedule, command, human}]}` (external = crontab lines outside the managed block, read-only) |
| POST | `/api/crons` | Cron fields | `Cron` (validates expression; syncs crontab) · `409 damaged_jobs` (jobs.json cannot be read: nothing is written) |
| PATCH / DELETE | `/api/crons/{id}` | | `409 damaged_jobs` as for POST |
| POST | `/api/crons/{id}/run` | – | `{ok}` (runs now in a transient unit) · `409 already_running` |
| GET | `/api/crons/runs?cron_id=&limit=50` | – | `[Run]` |
| GET | `/api/crons/{id}` | – | `Cron` |
| GET | `/api/crons/preview?schedule=` | – | `{valid, human, next:[at×5], error?}` (next runs in the configured time zone) |
| GET | `/api/crons/preview?once_at=` | – | `{valid, human, next:[at], once:true, error?}` (a one-time date, read in the configured time zone) · POST/PATCH with a past `once_at` -> `400 invalid_once` |

## Telegram
| GET | `/api/telegram` | – | `{configured, running, bot:{id, username, name}\|null, chat:{id, title, type}\|null, topics_enabled, mode:"simple"\|"threads"\|"mirror", threads:[{path, thread_id, name, session_id?}], agent_threads:[{path, thread_id, name}], settings:{mode, notify_crons, notify_system:bool(true), login_alerts, two_factor:bool, reply_mode:"progress"(default)\|"final", thread_days:int(30), mirror_web:bool (= mode "mirror")}, linking:bool, link:{code, deep_link, expires_at, expires_in, expired}\|null, poll_error, poll_error_code:"token_rejected"\|"conflict"\|"unreachable"\|null, sync_error, topics_notice, last_poll_ok, last_poll_age, last_error}` (special threads: path `"#crons"` / `"#alerts"` / `"#feed"`; session threads: `session_id`, path `""`). `mode`: `simple` (default of a new link: one chat - sessions without threads, their messages sent as replies, a reply continues the session; alerts in the main chat), `threads` (one thread per open session + Crons, Alerts, Notifications), `mirror` (threads + web turns copied). Not chosen yet in config.json: `threads` (or `mirror` if the old `mirror_web` was chosen) when the chat already has threads, else `simple`; the gateway writes it at start. A chat without threads (`topics_enabled:false`) works as `simple` whatever the mode. `running`: in the server, the poller itself; in another process (CLI, doctor), the `poller_pid` of the server's heartbeat is alive. `poll_error` is set and cleared only by the poller (getUpdates: 401 → `token_rejected`, the poller stops; 409 → `conflict`, another program reads the bot); `sync_error` only by the thread sync; `topics_notice` = threads are off for the bot (BotFather "Threaded Mode") - information, not an error. `last_poll_ok` = last successful getUpdates (Unix s, written at most every 30 s). `link` = the last link code, pending or expired (kept until a chat links). `last_error` (older readers) = `poll_error` or `sync_error`. Setup is done once a chat is linked (same rule as `/api/onboarding`) |
| POST | `/api/telegram/token` | `{token, password?}` | getMe, getWebhookInfo, then a short getUpdates probe → `{ok, bot}` · `400 {error, message}` with `error`: `bad_token` (bad format or rejected) · `unreachable` · `webhook_set` (the bot sends its updates to a webhook; also `pending_updates`) · `webhook_check_failed` (getWebhookInfo failed) · `conflict` (409: another program polls this bot). Saving the stored token again pauses our own poller during the probe. A different bot resets the chat link; the same bot (a new token after a revoke) keeps it. With two-step sign-in on, a token other than the stored one needs the current `password` (`401 bad_password`) |
| POST | `/api/telegram/webhook/remove` | `{token?}` | deleteWebhook (pending updates kept) for `token` (the one being saved) or the stored token → `{ok}` · `400 bad_token\|not_configured\|unreachable`. The UI then saves the token again |
| POST | `/api/telegram/link` | `{password?}` | `{code, deep_link, expires_at, expires_in}` (`https://t.me/<bot>?start=<code>`, valid 15 min) — starts polling and waits for `/start <code>` from a private chat; threads are synced right after linking. Empties the refused list. Messages dated before the link was created are ignored (a Start pressed too early); while a code is pending or expired less than 24 h ago, `/start` with a wrong, expired or no code gets "this link expired or is not valid - create a new one" (the chat is not refused) · `409 not_configured`. Also works with a chat linked: the new chat replaces it. With two-step sign-in on, needs the current `password` (`401 bad_password`) |
| GET | `/api/telegram/link` | – | `{linked, chat, pending:{code, deep_link, expires_at, expires_in, expired}\|null}` |
| POST | `/api/telegram/sync` | – | (threads modes; `simple`: nothing to do, `{created:0, deleted:0, …}`) makes the threads match: "Crons" + "Alerts" + one per open session (human, not archived, active in the last `thread_days` days, ≤ 50; created / renamed / deleted; a thread found deleted - on a send or a rename - is reopened for its session; Telegram has no silent check, so threads are not probed) → `{created:int, deleted:int, topics_enabled:bool, error:string\|null, notice:string\|null}` (topics disabled for the bot → `topics_enabled:false`, `notice` set and `error` null, everything goes to the main chat). Also automatic: a few seconds after any session change and every 10 min |
| PUT | `/api/telegram/settings` | partial settings (`mode`, `notify_crons`, `notify_system`, `login_alerts`, `reply_mode`, `thread_days` 1–365; `mirror_web` = older clients: true → mode `mirror`, false → `threads` when it was `mirror`) | `{ok, mode, deleting:int}` - to `simple`: the session threads and Crons / Alerts / Notifications are deleted from Telegram in the background (`deleting` = how many; agents' threads stay); to a threads mode: created by the next sync |
| POST | `/api/telegram/test` | – | sends a test message and checks the receiving side → `{ok, sent, poller:{running, last_poll_ok, last_poll_age, error, error_code}, webhook:{url, pending_updates, last_error}\|null, problems:[string]}` (`ok` = sent and no problem: poller stopped or in error, no getUpdates for 5 min, webhook set) · `409 not_linked` · `502 telegram_error` (not sent; same fields) |
| DELETE | `/api/telegram` | `{password?}` | unlink + forget token, threads and the reply map (`messages.db`). With two-step sign-in on (which this turns off), the current password is required: `401 bad_password` / `429 throttled` otherwise |

Agent threads (agent.json `telegram: true`): `config.telegram.agent_threads = {agent path: {tid, name}}`, one permanent
thread per agent named `🤖 <display name> · <project>/<topic>`, created on its first result, renamed when the name
changes, never deleted by the session sync, deleted with the agent. A message there = `agents.fire(trigger:
"telegram")` (the bot answers "⏳ <name> is on it." or why it did not start); threads off: results go to the main
chat with `🤖 <name>` in front, and a reply to one of them fires the agent the same way.

Replies (every mode): `state_dir('telegram')/messages.db` (SQLite) maps `"<chat>:<message id>"` -> `{sid}` or `{agent}`
(newest 5000, 60 days): the user's messages, the live status, the answers, the bell, `/sessions` cards. A message that
replies to a mapped one goes to that session (un-archived) or fires that agent, unless it is written in a session's own
thread. Alerts = events of the Notifications feed with buttons: `feed.py` calls `gateway.post_alert(ev)` /
`update_alert(ev)` with the feed event (`{id, source, level: info|success|warning|error, title, body, url, count, read,
actions:[{id, label, style}], ref, agent, resolved, resolution, telegram: off|silent|loud}`) - one message (the agent's
thread when it has the Telegram option, else Alerts / the main chat), nothing when `telegram` is `off` except a pending
request (`ref` `approval:…`), loud only when `loud`; a button per action (`open` / style `link` = URL button to
`public_url` + `url`, the others callback `al:<id>:<action>` -> `feed.act(id, action, by="telegram")`), edited on
update (`resolution`, no buttons once resolved). Without `feed.act` (older feed) the gateway posts the dashboard's
health problems itself every 60 s (not `cron_failed` nor
`login_failures`; button `h:<issue id>` = `health.mark_seen`; edited "Seen" / "Resolved"; off with `notify_system`).

## Backup
| GET | `/api/backup` | – | `{configured, repo, private:bool\|null, schedule, include:[glob], always:[glob], last:{at, ok, commit, files, error}\|null}` (`always` = CLAUDE.md/memory.md globs, always included) |
| POST | `/api/backup/config` | `{repo:"owner/name", token, create?:bool}` | verifies access/private/push (creates the private repo if asked; token may be omitted to keep the stored one) → `{ok, private, created?, warning?, error?}`; on success creates/updates the "Memory backup" cron job; `ok:false` while a backup or restore runs |
| PUT | `/api/backup/settings` | `{schedule?, include?}` | `{ok}` |
| POST | `/api/backup/run` | – | `{ok, commit, files, changed?, error?, code?, leaks?:[{file, kinds}]}` (`code`: `secret_found`, `public_repo`, `not_configured`, `git_failed`…; `409 busy`) |
| GET | `/api/backup/history?limit=100` | – | `[{at, ok, commit, files, changed, error, code?, duration_s}]` newest first |
| POST | `/api/backup/restore` | `{ref?}` | restores whitelisted files (current files saved to trash first) + cron jobs + server-independent settings → `{ok, files, restored:[path], unchanged, skipped:[path], crons:bool, mcp:int, held:{crons, extensions, hooks, mcp, review, outside?}, trash}` (local MCP servers and new jobs/extension code are held, see Backup docs) · `409 not_configured\|empty\|busy` |
| DELETE | `/api/backup` | – | forget repo + token (`409 busy` while a backup or restore runs) |

## Settings & secrets
| GET / PUT | `/api/settings` | `{timezone, language:"en"\|"fr", public_url, files_root, presentation_default?, usage_widget:bool, git_page:bool, infra_page:bool, mail_page:bool, maxxing_mode:bool, memory_max_lines:int, result_line_hidden:["model"\|"duration"\|"cost"\|"tokens"\|"cache"], donation_hidden:bool}` (`donation_hidden`: hides the donation links of What's new, Feedback and Settings -> License for every browser, default false; the Support card of Settings -> About stays) (`result_line_hidden`: parts of the line under each answer that are hidden, default `[]`, unknown values = 422, stored in canonical order) (`git_page`: the Git page `/git` and its sidebar entry, default false) (`maxxing_mode`: beta, Maxxing mode of the Sessions page - its switch, meter, driver and Alt+M -, default false) (`memory_max_lines`: 0 = no limit, else 50-5000, default 200) — a new `timezone` also switches the server zone (`timedatectl`, cron restarted); PUT ignores the fields equal to the stored config (neither checked nor applied: the web app sends the whole object) |
| PUT | `/api/settings/look` | `{theme:"dark"\|"light"\|"system", accent:"blue"\|"clay"\|"violet"\|"green"\|"amber"\|"rose", tint?:"neutral"\|"tinted"}` | `{ok, look}` · sent by the web app 600 ms after a change of theme / accent / tint (config `look`) · `422` bad value |
| GET / PUT | `/api/settings/profile` | `{name ≤32, color: "clay"\|"blue"\|"violet"\|"green"\|"amber"\|"rose"\|"teal"\|"zinc", emoji}` | `Profile` `{name, color, emoji, photo, photo_url}` (bus `profile`; PUT keeps the photo; `photo` = 16 hex of the photo's SHA-256, `""` = none) · `400 invalid_color\|invalid_emoji\|invalid_name` (a lone surrogate in `name` or `emoji` is refused) |
| GET / PUT / DELETE | `/api/settings/profile/photo` | PUT: the image bytes (JPEG, PNG or WebP by their first bytes, ≤ 512 KB; the UI sends a 256 px square) | GET the photo (`?v=` = version, cached for good); PUT / DELETE `Profile` · `400` `too_large` / `not_an_image` / `empty` (`maxxing/profile_photo.py`; Team contacts get the new version) |
| GET / PUT | `/api/settings/register` | `{count?, email?, news?, asked?}` (email: valid or `""`) | `RegisterState` `{count, count_blocked, email, news, asked, registered, error, synced_at}` (bus `register`). Optional hello to the authors (`maxxing/register.py`): `count` (default `true`) = anonymous daily signal (cloud id + version + `os`, `arch`, `health` codes), `count_blocked` = `MAXXING_NO_TELEMETRY` / `DO_NOT_TRACK` set in the service environment (counter off whatever `count`); `email` (+ `news`) adds pseudo and language; neither = cloud row archived (kept, never contacted again). An update never turns on the email or the news; 2.0.0a94 turned `count` on once where `asked` was false. |
| GET / POST | `/api/settings/feedback` | POST `{email, type: bug\|idea\|other, message, image?, forced?}` | GET `{email, version}` (prefill); POST `{ok}`. Feedback to the authors (`maxxing/feedback.py` -> cloud `/v1/feedback`). `forced: true` = sent although the check below had answered it (a note is added at the end of the message). Errors: 400 `invalid_email` / `message_required` / `too_long` / cloud codes, 429 `rate`, 502 `unreachable`, 503 `offline`. |
| POST | `/api/settings/feedback/check` | `{type: bug\|idea\|other, message}` | `{verdict: send\|answer\|self, answer, prompt, topic, checked}`. What this server's Claude makes of a message before it is sent (one read-only `claude -p` call over `docs/user`, `feedback.check`): `send` = a bug or a general idea, to send; `answer` = answered here (`answer`, markdown); `self` = specific to this installation: `prompt` is the request for a new session in `topic` (a topic of the project `system`, else the inbox). Never blocks: Claude missing, signed out, slow (90 s), busy with another check or unclear = `send` with `checked: false`. Nothing is sent to the cloud. Errors: 400 `message_required` / `too_long`. |
| GET / PUT / DELETE | `/api/settings/license` | PUT `{key}` (`HM-XXXX-XXXX-XXXX-XXXX`) | `{has_key, key_hint, kind, email, max_servers, expires_at, activated_at, enabled, moved_to_git}` (bus `license`, never the key). Optional Enterprise key: PUT = `license.activate` (cloud `/v1/activate`: checks it, counts this server; 400 `invalid_key` / `limit` / `revoked` / `expired` with the cloud message), DELETE = `remove_key` (frees the seat). Changes nothing else: code and updates stay on git. |
| GET | `/api/secrets` | – | `[{name, note, expose, updated, preview}]` (preview = first 4 chars + …, only `…` for values < 8 chars) |
| PUT | `/api/secrets/{name}` | `{value?, note?, expose?, create?}` | `{ok}` · `409 exists` with `create: true` when the name is taken · `400 invalid_name\|reserved_name\|value_required\|invalid_value\|invalid_note` (PATH, HOME…, MAXXING_* are reserved; a value has 1 to 16384 characters, no null byte, no lone surrogate) — `expose` = exported as env var to Claude sessions |
| GET | `/api/secrets/{name}/reveal` | – | `{value}` |
| DELETE | `/api/secrets/{name}` | – | `{ok}` |
| GET | `/api/secret-files` | – | `[{name, filename, size, sha256, note, expose, updated}]` (`sha256` = its first 12 hex characters; the full one stays in the metadata) - secret FILES of the Keys vault (`maxxing/vault_files.py`); no endpoint ever returns the content (a file is read on the server: `maxxing keys get-file`, or its path in the environment when `expose`) |
| PUT | `/api/secret-files/{name}?note=&expose=&create=&filename=` | raw body = the file (`application/octet-stream` or no type, 1 byte to 1 MiB, read in chunks and refused past 1 MiB). Query: `note` (≤ 200 chars), `expose` (bool), `create` (bool), `filename` (original name, display only, ≤ 100 chars after sanitizing) | `{ok}` · an empty body on an existing name changes only `note` / `expose` / `filename`, the file is kept · `409 exists` with `create=true` when the name is taken by a file, `409 name_taken` when it is a text key (and `PUT /api/secrets/{name}` answers `409 name_taken` for a name that is a file) · `400 invalid_name\|reserved_name` (same rules as keys) `\|file_required` (new name, empty body) `\|invalid_value` (over 1 MiB) `\|invalid_note` · `413 too_large` over 1 MiB · `415 unsupported_media_type` for any other `Content-Type` (multipart included). `expose` = the environment variable `NAME` of every Claude session and shell cron job holds the file's **path**, never its content |
| DELETE | `/api/secret-files/{name}` | – | `{ok}` · removes the file and its entry · `404 not_found` |

## MCP servers
Claude Code's MCP servers (maxxing/mcp.py), shown in Settings -> MCP. Bus topic `mcp`.
```
McpServer = {id:"<scope>|<folder>|<name>", name, scope:"user"|"local"|"project",
  where:{rel:"projects/acme/topics/ads"|null, project, topic, agent (an agent folder: projects/*/topics/*/agents/*), exists, path:"/abs/folder"|null},
  type:"http"|"sse"|"stdio", url?, command?, args?, headers?, env?,   (secrets shown as "•••": every header / env
    value that is not only ${KEY} references (an auth scheme word aside; Content-Type, Accept... stay), the
    user:password and query values of url)
  literal_secret:bool, keys:[vault names referenced as ${KEY}],
  state:"connected"|"needs_auth"|"failed"|"pending"|"unknown", detail, checked_at, approved? (project scope)}
```
| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/mcp` | – | `{servers:[McpServer], checking, checked_at, config_file, auto}` (first call starts a check; `auto` = config `mcp_auto`) |
| PUT | `/api/mcp/auto` | `{enabled}` | `{ok, enabled}` - config `mcp_auto` (turning it on starts a check: it lists the claude.ai connectors) |
| POST | `/api/mcp/check` | – | `{checking:true}` - `claude mcp list` per folder in the background, then bus `mcp` |
| POST | `/api/mcp` | `{name, where:"" \| "projects/…", type:"http"\|"sse"\|"stdio", url?, command?, args?, headers?, env?}` | `{id, exposed:[vault keys now exposed]}` · `400 bad_name\|bad_url\|bad_command\|bad_type\|bad_where\|too_long` (a value over 8192 characters, or 32768 in all), `404 folder_missing`, `409 exists` |
| DELETE | `/api/mcp?id=` | – | `{ok}` |
| POST | `/api/mcp/login` | `{id}` | `{login, url}` - runs `claude mcp login --no-browser` in a pseudo-terminal; replaces an attempt already open for that server · `400 no_login_url`, `404 folder_missing\|not_found` (no such server), `429 too_many_logins` (4 attempts of other servers open), `500 no_claude\|cli_failed` |
| POST | `/api/mcp/login/{login}` | `{redirect}` (the localhost callback URL) | `{ok, message}` · `400 bad_redirect\|login_failed`, `404 login_expired` (also cancelled meanwhile), `409 busy` (already being finished), `504 timeout` |
| DELETE | `/api/mcp/login/{login}` | – | `{ok}` |

## Browser of my PC
`maxxing/pcbridge.py` + `api/pc.py`. One paired PC runs the Harness PC agent (`pc-agent/`, contract
`pc-agent/PROTOCOL.md`); Claude reaches its browser through the user-scope MCP `harness-pc`.
```
PcStatus = {available, device:{id,name,os,arch,browser,browsers,version,created,last_seen}|null, online,
  browser_running, mcp_running, last_use|null, mcp_registered, pairing:{expires_at,browser,os}|null,
  candidate, settings:{idle_min}, browsers:[…], targets:[…], actions:[{at,tool,ok,ms,args:{url?,…}}]}   (newest first, 20)
available = a Harness PC can be downloaded (MAXXING_PC_BIN_DIR, or files listed in pc_agent.json); the UI hides the
  card while it is false and no PC is paired
candidate = {id,name,os,arch,version,created,ip}|null in PcStatus: a PC that paired with a code and waits for the user
PcPairing = {code, expires_at, expires_in, server, downloads:{<target>:url}, commands:{windows,darwin,linux}}
target = windows-amd64|windows-arm64|darwin-arm64|darwin-amd64|linux-amd64|linux-arm64
```
| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/pc` | – | `PcStatus` |
| POST | `/api/pc/pairing` | `{browser, os, autostart?}` | `PcPairing` (code valid 15 min, replaces the previous one) · `422 invalid`, `409 no_agent` (nothing to download) |
| POST | `/api/pc/confirm` | `{id, ok?:true}` | `{ok}` - yes: the candidate becomes the PC (replaces the previous one, MCP registered); no: its agent gets `unpair` · `ok:false` when it is not the candidate or expired (15 min) |
| PUT | `/api/pc/settings` | `{idle_min}` (1–240) | `{idle_min}` |
| POST | `/api/pc/stop` | – | `{ok}` - closes the browser and the tools |
| POST | `/api/pc/wipe` | – | `{ok}` · `409 offline`, `502 pc_error` |
| POST | `/api/pc/test` | – | `{ok, text}` (`list_pages` through the MCP path) |
| POST | `/api/pc/mcp/register` | – | `{ok}` · `409 not_paired` |
| DELETE | `/api/pc` | – | `{ok}` - unpairs (the agent removes its autostart and exits), MCP removed |
| POST | `/api/pc/pair` | `{code, name, os, arch, version, browsers}` | `{device_id, token}` - the PC is a `candidate` until `/confirm` · public, `403 bad_code\|expired` |
| GET | `/api/pc/download/{target}?code=` | – | the agent binary + config trailer, streamed from the cached agent (`Content-Length` set) · public, `403`, `404` |
| GET | `/api/pc/install.ps1\|sh?code=&target=` | – | install script (downloads, starts) · public |
| WS | `/api/pc/ws` | `Authorization: Bearer <device token>` | agent control + DevTools frames (PROTOCOL.md) · close `4401` |
| WS | `/api/pc/cdp` | `X-PC-Secret` | loopback only: DevTools relay for chrome-devtools-mcp · close `4403` |
| POST | `/api/pc/mcp` | JSON-RPC, `Authorization: Bearer <mcp secret>` | loopback only: MCP (streamable HTTP, JSON) `initialize`, `ping`, `tools/list`, `tools/call` · `403` - a `url` of the PC itself or its local network (localhost, private / link-local IPs in any IPv4 form, bare names, `.local`, `.lan`…) is refused like `file:` |

## Voice (speech-to-text)
Claude cannot listen: audio is transcribed on the server (web mic button + Telegram voice notes).
```
VoiceStatus = {settings:{engine:"off"|"local"|"groq"|"openai", model:"tiny"|"base"|"small"|"medium", language:"auto"|"<iso>", auto_send:bool, direct:bool},   // direct (default true): the web mic sends the recording at once
  ready:bool, reason:"off"|"no_ffmpeg"|"not_installed"|"no_key"|null, ffmpeg:bool,
  local:{installed, loaded:str|null, recommended, ram_gb, cpus, models:[{id, size_mb, present}]},
  keys:{groq:bool, openai:bool}, key_names:{groq:"GROQ_API_KEY", openai:"OPENAI_API_KEY"},
  install:{state:"idle"|"running"|"done"|"error", step:"deps"|"model"|null, progress:0..1|null, model, message, error, at},
  max_seconds:900}
```
| GET | `/api/voice` | – | `VoiceStatus` (the UI polls it every second while `install.state = running`) |
| PUT | `/api/voice/settings` | partial settings | `{ok, settings}` · `400 invalid_language` · `422` bad enum. Default model when never chosen: `small` (`base` with < 4 GB RAM) |
| POST | `/api/voice/install` | `{model?}` | starts the background job: `uv sync --extra voice` when faster-whisper is missing, then the model download → `install` object · `409 busy` |
| DELETE | `/api/voice/models/{model}` | – | `{ok}` (deletes a downloaded local model) |
| POST | `/api/voice/transcribe` | multipart `audio` (+ form `path`? topic path, `language`?) | `{text, language, duration_s, engine, model, ms, audio_path}` — `path` keeps the original file in `<topic>/attachments/voice/YYYY-MM/` (`audio_path`, else null). Any format ffmpeg reads (webm/opus, ogg/opus, m4a, mp3, wav, mp4), ≤ 100 MB, ≤ 15 min · `409 voice_off` · `503 not_installed\|no_key\|no_ffmpeg` · `413 too_long\|too_large` · `422 bad_audio\|empty_audio` · `502 engine_error\|bad_key\|download_failed` |

Telegram: voice notes and video notes in a session thread (not audio files: attachments) are downloaded, transcribed, echoed as
`🎤 <transcript>` and sent to the session as the user message (attachment = the audio file). Engine off → a hint.

## System
| GET | `/api/system/health` | – | `{ok, issues:[{level, code, text}], cpu_pct, load, mem:{total,avail}, disk:{total,free,pct}, uptime_s, claude_auth, claude_auth_error, claude_checked_at, backup_age_h, failed_logins_1h, at}` (each issue also has `id` and `seen`; issue `claude_auth`: "Claude is not connected" or "Claude sign-in expired…") (cached 30 s, `?force=1`) |
| POST | `/api/system/health/seen` | `{id, seen=true}` | the health above, fresh - marks a current issue as seen (or not): it stops counting in the sidebar dot until its text changes (numbers left out of the `id`) or for 24 h; marks in `<state>/health-seen.json` · `404 not_found` |
| GET | `/api/system/services` | – | `[{name, label, active:bool, enabled:bool, since:float\|null, state}]` (claude-maxxing, caddy, tailscaled, cron + config `services_extra`; units not installed are omitted; one `systemctl show` call, cached 10 s, dropped by a service action) |
| POST | `/api/system/services/{name}/{start\|stop\|restart}` | – | `{ok}` (self restart deferred 2 s) |
| GET | `/api/system/logs?unit=&lines=200` | – | `{lines:[str]}` |
| GET | `/api/system/version?refresh=1` | – | `{version, commit, latest_commit\|null, behind:int\|null, checking:bool, checked_at:float\|null, custom:{count, titles, dirty, rebase}, pending:{at, reason:"conflict"\|"health"\|"dependencies", target_version?, conflicts?}\|null, license:{enabled, key_hint, email, kind, updates_until, expires_at, channel, latest, message, max_servers, moved_to_git, move_error}, report:{at, version, ok, problems}\|null, after:{to, at, notes_session?, notes_path?, done}\|null}` (remote checked every 10 min with git and the update token; nothing on an install still on archives until it has moved to git; `refresh=1` checks now and waits; `commit` and `custom` count/titles/dirty are cached 30 s and while the clone's HEAD / branch ref / index are unchanged, `refresh=1` re-reads them, `rebase` and `pending` are always fresh) |
| POST | `/api/system/update` | – | `{ok}` starts `maxxing update --smart` in a transient unit (after the restart the server verifies, then opens the upgrade-notes session) |
| GET | `/api/system/update/preflight?refresh=` | – | `Preflight` = `{ok, verdict: up_to_date\|simple\|adapt, current, latest, behind, customs:[{id, title, why, files, status: ok\|review\|included\|conflict\|unknown, conflicts, overlap}], unsaved, unsaved_overlap?, web_changes (dirty files under web/dist), ui_build?: {status: ok|failed, error, seconds} (only when a customization changes the web sources), extensions:[{id, name, api, reason}], notes:[{version}], changelog}` - the update simulated in a throw-away git worktree; cached until HEAD / target / unsaved files change; `refresh` fetches first · `502 preflight_failed` |
| POST | `/api/system/update/assist` | – | `{session}`: a session in the update topic that adapts this server's changes then updates |
| GET | `/api/system/update/report` | – | `{report}` = last verification `{at, version, ok, problems, extensions:[{id, name, type, ok, error, skipped?}], checks:[{id, title, check, ok, output}]}` or null |
| POST | `/api/system/update/verify` | – | `{report}`: verify now |
| POST | `/api/system/update/fix` | – | `{session}`: a session that fixes what the last report found · `409 nothing_to_fix` |
| PUT | `/api/system/auto-update` | `{enabled: bool}` | `{ok, enabled}` (config `auto_update`: Settings -> Updates, update by itself while nobody is on the interface and nothing runs) |
| GET | `/api/system/changelog?limit=10` | – | `{version, entries:[{version, label, current:bool, body:markdown}]}` newest first, parsed from the public `CHANGELOG.md` (`2.0.0-alpha.6` matches `2.0.0a6`); `limit` 1-500 (Settings -> Updates asks 500) |
| GET | `/api/usage` | – | experimental Claude plan usage `{available, five_hour:{pct (0-100 or null), resets_at (Unix s, null when missing or out of range)}\|null, seven_day:{…}\|null, reason?, stale?, retry_at?}` (off unless settings `usage_widget`; 60 s cache, `?force=1`). Token: the stored long-lived `claude_oauth_token` first, else the `claude login` credentials file. `reason`: `disabled`, `no_oauth_credentials`, `api_key` (no plan usage with an API key), `rate_limited` (429: no call before `retry_at` = now + Retry-After, even forced; the last good values are returned with `stale`), `http_<status>`, or an exception name |

## Import (from another agent)
Zip layout and merge rules: `server/maxxing/importer.py` and docs/user/21-import.md.
| GET | `/api/import/prompt?agent=hermes\|claude-code\|openclaw\|other` | – | `{agent, agents, prompt}` |
| POST | `/api/import/upload` | multipart `file` (≤ 600 MB) | preview, writes nothing → `{id, name, projects:[{name, exists, topics:[{name, source, files, exists}]}], skills, aside, root_memory, files, size, skipped:[{file, reason}], secrets:[{file, kinds}], renamed:[{from, to}]}` · `400 bad_zip\|empty` · `413 too_big\|too_many_files` |
| POST | `/api/import/{id}/apply` | – | imports (never overwrites: memory/CLAUDE.md get an "## Imported" section, other files `<name> (imported)`, skills `<name>-imported`; files with secrets refused; Claude Code settings and Harness folder settings `.maxxing.json` / `.order.json` refused; a file whose place is taken by a folder, sits behind a file, or would be written through a link leading out of the workspace is added to `skipped` and the import goes on) → `{ok, projects, topics, files, merged, renamed, skills, aside, secrets, skipped, folder, report, finish_prompt}` · `400 bad_zip` · `404 not_found` (expired, 24 h) · `409 busy` (another import is being applied) `\|conflict` |
| DELETE | `/api/import/{id}` | – | forgets an upload → `{ok}` |

## Agents

Settings -> Features -> Agents (`agents_page`, off by default): every route below answers `404 feature_off` while it
is off. An agent = a folder `projects/<p>/topics/<t>/agents/<a>/` (CLAUDE.md role + memory.md + agent.json, see
INTERNALS.md#agents); its path is a session path. Every trigger goes through `agents.fire()` (guards: `enabled`,
`limits.usd_per_day`, `limits.runs_per_hour`, hops) and starts a NEW session (`source: "agent"`, `cron: true`).

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/agents` | – | `{agents: [Agent & Status], avatar: {color: [..], skin: [..], hair: [..], hair_color: [..], face: [..], accessory: [..]}}` (the pixel-art character's parts; `color` = an accent colour of the UI, unknown or missing values = a stable pick from the agent's name) |
| GET | `/api/agents/templates?lang=` | – | `{templates: [AgentTemplate]}`: the gallery of ready-made agents (`maxxing/agent_templates.py`), texts in `lang` (default: UI language; English when missing). `AgentTemplate = {id, name, summary, role, needs, brief (the four-line message an idea puts in a new agent's box), first (one of the six ideas shown first), avatar, permission_mode, approvals, allowed_tools, keys, keys_present, limits, cron?: {schedule, prompt}, webhook?: {kind, prompt}}`; nothing is created (the UI fills its form, `maxxing agents create --template`) |
| POST | `/api/agents` | `{topic_path, name, display_name?, description?, template?, ...AgentFields}` (`template`: a ready-made agent id, its settings under the fields) | `Agent & Status` · `400 bad_template` / `bad_path` / `invalid_name` / `bad_trigger` / `bad_model` / `bad_permission_mode` · `404 not_found` (topic) · `409 exists` / `too_many` (20 per topic) |
| GET | `/api/agents/{p}/{t}/{a}` | – | `Agent & Status & {crons: [CronJob], webhooks: [{id, name, kind, url, has_secret}], trigger_stats: {<trigger id>: {events, last_event_at}}}` (cron jobs whose `topic_path` is the agent path; the feed hooks behind its webhook triggers, never their secret; events of each feed trigger's source over the feed retention) · `404` |
| PATCH | `/api/agents/{p}/{t}/{a}` | `{display_name?, description?, ...AgentFields}` | `Agent & Status` (`limits` and `avatar` are merged; `description` rewrites the role in CLAUDE.md) |
| DELETE | `/api/agents/{p}/{t}/{a}` | – | `{ok}`: folder + sessions to the Trash, its cron jobs deleted, its thread, state and Telegram thread dropped · `409 has_running_sessions` |
| GET | `/api/agents/{p}/{t}/{a}/thread?limit=100&before=<at>` | – | `{messages: [AgentMessage]}` oldest first (the Activity tab) |
| GET | `/api/agents/{p}/{t}/{a}/media-roots` | – | `{roots: [abs path]}` the folders whose files the agent's answers may link and preview on its page: its folder + its `writable` folders, minus any that is, holds or sits in a secret / private path (`agent_guard.media_roots`); the page passes the one holding a file as `within` to `/api/files/thumb`, `/raw`, `/stat` · `404` |
| POST | `/api/agents/{p}/{t}/{a}/run` | `{text?, reply_to?, attachments?:[filepath] (≤ 10)}` (`attachments`: uploaded first with `POST /api/uploads?path=<agent path>`, each a regular file under `<agent>/attachments/` with no link below it, else `400 bad_attachment`; files only = the text "See the attached files."; the thread's `run` message keeps `attachments`) | `{started: true, session: Session, continued?: true}` \| `{started: false, reason: "disabled"\|"budget"\|"rate"\|"depth"\|"missing"}` - the text is the user's task (not framed). `reply_to` = a thread message id: its session goes on with the text (`continued`, no new session; a gone session -> a new one). A new session gets the last 3 results of the thread as framed context |
| POST | `/api/agents/{p}/{t}/{a}/seen` | – | `{ok}`: the thread is read (`thread_unread` 0) and the finished, read runs are archived (`agents.tidy`) |
| POST | `/api/agents/{p}/{t}/{a}/triggers/{tid}/test` | – | `{event: FeedEvent}`: a sample feed event on the trigger's source (its first level, its `match` words), so the agent starts as for a real one · `404 not_found` |
| POST | `/api/agents/{p}/{t}/{a}/webhook` | `{kind: "generic"\|"stripe"\|"shopify"\|"github", prompt?, levels?, match?}` | `{agent, hook: FeedHook}`: a feed hook named `<topic>-<agent>` + a feed trigger on its source |
| GET | `/api/agents/layout` | – | `AgentsLayout = {projects: [name], colors: {project: color}, agents: {project: [agent path]}}`: the order and project colours picked by hand on the Agents page (`<state>/agents/layout.json`, the same on every device; missing = default order: projects in workspace order, agents by topic then name, colour = a stable pick from the name). Names that no longer exist are kept; the UI sorts listed ones first, then the rest in the default order |
| PUT | `/api/agents/layout` | `AgentsLayout` (each key optional, the whole layout is replaced) | `AgentsLayout` · `400 bad_layout` (not a project name, a colour outside `avatar.color`, an agent path of another project, more than 500 projects or 500 agents per project). Bus `agents`; the colour of a project is also the outfit of its new agents (`agents.project_color`) |
| GET | `/api/agents/sandbox` | – | `{ok, missing: ["bwrap"\|"socat"\|"apparmor"\|"linux"]}`: what Claude Code's sandbox needs on this server (`agent_guard.available`) |
| POST | `/api/agents/import` | `{topic_path, markdown, name?}` | `Agent & Status & {ignored: [string]}`: a Claude Code agent file (`agent_format.parse_md`) made an agent (sandbox on, no trigger) · `400 bad_file` + the create errors |
| GET | `/api/agents/{p}/{t}/{a}/export` | – | `text/markdown` attachment `<a>.md`: the agent as a Claude Code agent file |
| POST | `/api/agents/{p}/{t}/{a}/runs/{sid}/continue` | – | `{session: Session}`: a copy of run `sid` as a normal session of the topic (`from_agent: {path, session}`), its log copied and its Claude transcript copied to the topic's project folder (same `csid`, resumed from there) · `404 not_found` (not a run of this agent) · `409 busy` |
| POST | `/api/agents/{p}/{t}/{a}/crons` | `{name?, schedule?, prompt?, enabled?}` | `CronJob` (`kind: "claude"`, `topic_path` = the agent path, `notify: "never"`) |

```
AgentFields = {avatar?: Avatar, enabled?: bool, model?: string, permission_mode?: ""|"bypass"|"acceptEdits"|"default",
               allowed_tools?: [string], disallowed_tools?: [string], telegram?: bool, approvals?: bool,
               trust_outside?: bool, keys?: [string] (vault names, max 50; 400 bad_key), limits?: Limits,
               triggers?: [Trigger], sandbox?: bool, domains?: [host] (max 50), writable?: [folder] (max 20),
               rules?: [Rule] (max 20), subagent?: bool}
               approvals: every run asks before risky tools; a run started by outside text (feed / webhook event,
               another agent, `run --data`: session env MAXXING_AGENT_OUTSIDE=1) asks unless trust_outside.
               keys: the only vault entries its runs get as env vars (none by default, exposed or not).
Agent  = {path, project, topic, name (folder slug), display_name, description, avatar: Avatar, enabled, model,
          permission_mode, allowed_tools, disallowed_tools, telegram, approvals, trust_outside, keys, limits: Limits,
          triggers: [Trigger], sandbox: bool (false when missing: agents made before the sandbox; new ones: false, true with a mailbox or a feed trigger),
          domains: [host] (sandbox network allow list, "*.x" ok), writable: [folder of the topic, "." = all],
          rules: [{tool: "Bash"|"Write"|"Edit"|"WebFetch"|"*", match, reason}], subagent: bool,
          created, session_count, archived_count, running, unread}
Status = {cost_today: number (USD, sessions of the agent today), runs_last_hour: int, last_run: AgentMessage|null
          (last result or skip), running_now: int, running_sessions: [{id, title, started}],
          thread_unread: int (results after the last `seen`), waiting: int (approval requests pending),
          alerts: int (its open, unread feed alerts other than requests: failed run, budget, runs/h, broken trigger)}
Rule   = {tool: "Bash"|"Write"|"Edit"|"WebFetch"|"*", match: string, reason: string}
Avatar = {color (outfit), skin, hair, hair_color, face, accessory}   each one of the names listed by GET /api/agents (unknown -> default)
Limits = {usd_per_day: 2.0 (0 = none), runs_per_hour: 6 (0 = none), timeout_s: 1800, debounce_s: 60,
          approval_timeout_s: 1800}
Trigger = {id: "t_<hex>", kind: "feed", enabled, source (feed source), levels: [info|success|warning|error] ([] = all),
           match (substring of title / body, "" = any), prompt, hook_id? (the feed hook made for it)}
AgentMessage = {id, at, kind: "note"|"run"|"skip"|"result", text,
                trigger?: "manual"|"cron:<job>"|"feed:<trigger>"|"telegram"|"agent:<path>", source?,
                session?: sid, reason? (skip), ok?: bool (result), cost?: number|null (result), status? (note),
                outside?: true (result of a run started by outside text: left out of the owner's new conversation; another start that gets it as context asks first),
                reply_to?: message id (run that continued a session), attachments?: [filepath] (run)}
```
Bus topic `agents` on every change of an agent or of its thread (and `workspace` for the tree). CLI:
`maxxing agents list | run <agent> [text] [--data] | send <agent> <text> | on <agent> | off <agent> | templates |
create <p>/<t>/<a> | show | cron | webhook | watch | export <agent> | import <file> --topic <p>/<t> | sandbox-setup`
(docs/user/17-cli-reference.md). The working directory of an agent turn is the agent folder.

## Sandbox, rules, subagents (agent_guard.py, agent_format.py)

A turn in an agent folder gets one `--settings` (spawn.settings_args merges the server deny rules with
`agent_guard.settings`): with `sandbox`, `sandbox: {enabled, allowUnsandboxedCommands: false, failIfUnavailable: true,
autoAllowBashIfSandboxed: true, excludedCommands: ["maxxing:*"], filesystem: {denyRead: secret_paths(), allowWrite:
[agent folder, writable...]}, network: {allowedDomains: domains}}` + `permissions.deny` Read/Edit on the same secret
paths (the sandbox covers shell commands only) + `permissions.allow` `Bash(maxxing:*)` (an excluded command still needs a
permission, else it runs inside) and `WebFetch(domain:<d>)`; `--add-dir` per writable folder; the mode is never
bypass (`agent_guard.mode`: Claude Code lets every domain through in bypass -> acceptEdits). Sandbox unavailable
(`available()`: bwrap, socat, AppArmor profile when kernel.apparmor_restrict_unprivileged_userns=1) -> the turn
fails before Claude starts. With `rules`: `hooks.PreToolUse` = `<python> -m maxxing.agent_guard hook <agent path>`
(deny + reason). The `maxxing` CLI refuses everything but `CLI_ALLOWED` when its process belongs to the systemd unit
`maxxing-<sid8>` of a session in a sandboxed agent folder (`/proc/self/cgroup`, not an env var the turn could
change). A session in a topic gets `--agents <json>` with the topic's agents that have `subagent` on
(`agent_format.subagents`). Tests: `MAXXING_SANDBOX_CHECK=0` skips the availability check.

## Agent groups

In the Agents page (same `agents_page` switch: `404 feature_off` while off). A group = a folder
`projects/<p>/groups/<g>/` (`CLAUDE.md` = its goal, `group.json`, `files/` = the shared folder) whose members are 2-6
agents of project `<p>`; only the owner writes to it, its members answer one turn at a time (`agent_rooms.py`, see
INTERNALS.md#maxxing.agent_rooms).

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/agent-groups` | – | `{groups: [Group]}` (every project, sorted by project then folder) |
| POST | `/api/agent-groups` | `{project, name (folder slug), display_name?, emoji?, goal?, members: [{path, role?}], lead?, shared_files?, trust_members?, limits?}` | `Group` · `400 invalid_name` / `bad_member` (not an agent of the project) / `members` (not 2-6) · `404 not_found` / `unknown_member` · `409 exists` / `too_many` (20 per project) |
| GET | `/api/agent-groups/{p}/{g}` | – | `Group` · `404 not_found` |
| GET | `/api/agent-groups/{p}/{g}/media-roots` | – | `{roots: [abs path]}` the group's folder + each member's media roots (`agent_rooms.media_roots`) · `404` |
| PATCH | `/api/agent-groups/{p}/{g}` | the create fields but `project` / `name` (`limits` merged; `goal` rewrites CLAUDE.md; `members` checked like create, except a former member whose agent was deleted: dropped) | `Group` (+ `dropped: [path]` when such members were dropped; members removed: their group session and queued turns dropped) |
| DELETE | `/api/agent-groups/{p}/{g}?keep_files=` | – | `{ok}`: turn stopped, folder and room deleted; `keep_files=true` moves `files/` to `projects/<p>/groups/.kept-<g>-<unix time>/` first. Members and their sessions stay |
| GET | `/api/agent-groups/{p}/{g}/messages?limit=200&before=<at>&after=<at>` | – | `{messages: [GroupMessage]}` oldest first (`after`: only the newer ones, how the group page refreshes) |
| POST | `/api/agent-groups/{p}/{g}/uploads` | multipart `file` (one or more) | `{files:[Upload]}` saved under `<group>/attachments/YYYY-MM/` (as `/api/uploads`: limits, never through a symbolic link: `400 bad_path`) |
| POST | `/api/agent-groups/{p}/{g}/messages` | `{text, attachments?:[filepath] (≤ 10, from .../uploads, else 400 bad_attachment)}` (≤ 4000; text or files) | `{message: GroupMessage, queued: [agent path]}`: the owner's message (the same text again within 3 s: `{message: <the first>, queued: [], duplicate: true}`, posted once); the members named (`@slug`, `@all`/`@everyone`/`@tous`; none: the lead, else the last member who spoke, else the first not paused) are queued (replacing pending hand-overs) and the first starts unless a turn runs. `stop @slug` pauses that member (a message holding only stops queues nobody); naming a paused member resumes it · `400 empty` |
| POST | `/api/agent-groups/{p}/{g}/stop` | – | `{ok}`: queue emptied, the running turn stopped (`service.stop`); its answer is still posted, it hands over to nobody |
| POST | `/api/agent-groups/{p}/{g}/reset` | – | `{ok}`: "New topic" - stop, then every member starts a new session at its next turn |
| POST | `/api/agent-groups/{p}/{g}/seen` | – | `{ok}`: `unread` 0 |
| POST | `/api/agent-groups/{p}/{g}/members/{mp}/{mt}/{ma}/pause` | `{paused: bool}` | `Group` · `404 not_member` |

```
Group = {path: "projects/<p>/groups/<g>", project, name, display_name, emoji, goal (CLAUDE.md description),
         members: [{path, handle (its @name: the folder name; when two members share it, from the display name, else <topic>-<folder>; stored in group.json), slug (= handle), role, exists, display_name, avatar, enabled, paused, speaking}], lead (member path|""),
         shared_files: bool (default true), trust_members: bool (default true),
         limits: {waves: 3 (1-6), replies: 10 (1-30), per_hour: 40 (1-200)}, created,
         files_path ("projects/<p>/groups/<g>/files" | "" when shared_files is off), busy (a turn runs or is queued),
         speaking (member path | ""), speaking_session (sid | ""), last_at, unread: 0|1}
GroupMessage = {id, at, kind: "message"|"pass"|"skip"|"note"|"stop", author: "me"|<member path>|"", text,
                session? (the member's group session), cost?, reason? (skip: disabled|budget|busy|missing|failed|error),
                limit? (note: waves|replies|per_hour), reset? (note of New topic),
                attachments?: [filepath] (the owner's message: sent to the members who answer it the first time they see
                it - `_origin_files`; its paths are in the text of every turn)}
```
Turns: a member keeps one session per group (`state.sessions`), continued with `service.send_message`; a new one is
`create_session(<agent path>, source "agent", cron true, env {MAXXING_AGENT, MAXXING_AGENT_TRIGGER: "group:<path>",
MAXXING_AGENT_DEPTH: 0, MAXXING_AGENT_GROUP: <path>})`. The agent's `gate()` applies except `rate` (the group's limits
replace runs per hour). `run_settings(path, outside, session, group)` adds `files/` to `writable` and makes the turn
outside (approvals forced unless `trust_outside`) when it is a hand-over and `trust_members` is off. The answer
(`last_assistant_text`) is posted by `agents.on_turn_end` -> `agent_rooms.on_turn_end`: `PASS` / empty = `pass`; the
members it names are queued as the next wave. The member's thread gets `run` / `result` lines with `group: <path>`
(no Telegram message for group turns). Bus topics `agent-groups` and `agent-groups:<path>`. CLI:
`maxxing agents group list | show <p>/<g> | create <p>/<g> --member A[=role]... | update <p>/<g> ... | say <p>/<g> <text>` (`group` is in
`agent_guard.AGENT_OWNER_ONLY`: refused in every agent turn).

## Approvals

A turn of an agent with `approvals: true` runs in permission mode `default` with
`--permission-prompt-tool mcp__maxxing-approval__approve` (`maxxing/approval_mcp.py`, a stdio MCP server started by
Claude Code): every tool call that is not pre-allowed (`allowed_tools`) waits for the user. Bus topics `approvals` +
`sessions` on every new / decided request. A request nobody answers is denied after the agent's
`limits.approval_timeout_s` (default 1800 s); a stopped turn marks its requests `expired`. A run started by outside text
(`MAXXING_AGENT_OUTSIDE=1`) asks too unless `trust_outside`. With Telegram linked, each pending request is also posted
(agent thread when its `telegram` option is on, else Alerts) with Allow / Deny buttons (callback `p:<id>:allow|deny`,
decided with `by: "telegram"`); the message is edited when the request ends, wherever it was answered.

```
Approval { id: string (16 hex), session: string, agent_path: string, tool: string, input: object (clipped, secrets
           redacted), summary: string ("Bash: git push"), at: number, expires: number,
           status: "pending"|"allow"|"deny"|"timeout"|"expired", message: string, decided_at: number|null }
```

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/approvals?session=<sid>` | – | `{approvals: [Approval]}` waiting ones, oldest first |
| POST | `/api/approvals/{id}` | `{decision: "allow"\|"deny", message?}` | `Approval` (`404 not_found`, `409 not_pending` when answered, timed out or expired) |

## Docs
| GET | `/api/docs` | – | `[{slug, title, section, order}]`; `?full=1` adds `markdown` to every page (full-text search, one request) |
| GET | `/api/docs/{slug}` | – | `{slug, title, markdown}` |

## Git

Read-only (`maxxing/gitview.py`). `repo` = an absolute path of a clone inside the files root (a sub-folder resolves
to its clone), or `github:owner/name` (every GitHub token of the server: vault keys whose value looks like one - any name - plus `GITHUB_TOKEN` / `GH_TOKEN` and the backup token; a repository call uses a token that listed it, then the others). Errors: `400 bad_path|bad_sha|
bad_repo|git_failed`, `403 outside_root`, `404 not_a_repo|not_found|no_branch`, `401 bad_token`, `400 no_token`,
`502 github_unreachable|github_error`, `504 git_timeout`.

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/git/repos?refresh=` | – | `{root, local:[{path, name, branch, upstream, ahead, behind, changed, untracked, last_commit, last_subject, remote, github, error, worktrees}], github:{connected, login, accounts:[{login, name, avatar, keys:[key name], repos}], errors:[{key, error}], error, repos:[{full_name, owner, name, description, private, fork, archived, permission: admin\|maintain\|push\|triage\|pull\|none (best of the tokens), default_branch, pushed_at, url, language, stars, open_issues, keys, accounts, local_paths}]}}` (token values never returned) — cached 60 s (`refresh=1` rescans); clones found under the files root, depth ≤ 6, `node_modules`-like and dot folders skipped, a clone's tree not searched; linked worktrees of a listed clone counted in its `worktrees`, not listed; remote URLs without credentials |
| GET | `/api/git/graph?repo=&limit=200&branches=a,b` | – | `{repo:{kind: local\|github, id, name, branch, github, ...summary or {url, private, permission, description, branches, branches_shown}}, commits:[{sha, parents, refs:[{name, kind: head\|branch\|remote\|tag, current?}], author, date, subject}], truncated}` — newest first, children before parents; subject and author cut at 500 characters (`…`); limit ≤ 1000; GitHub = default branch (100) + the 12 other branches (40 each) merged |
| GET | `/api/git/commit?repo=&sha=` | – | `{sha, parents, author, email, date, message, files:[{path, additions, deletions}], files_total, url?}` (a merge: diff against its first parent; message cut at 50 000 characters (`…`); ≤ 300 files; an annotated tag shows its commit; `sha` is an object id, never a branch or tag of that name; 404 `no_commit` for a tree or blob id) |
| GET | `/api/git/pulls?repo=github:owner/name` | – | `[{number, title, author, head, base, draft, url, updated}]` (open, 30) · `400 not_github` |

## Infra

Inventory (`maxxing/infra/`, Settings -> Features -> `infra_page`, off by default). One snapshot
(`<state>/infra/snapshot.json`) refreshed in the background (`infra_refresh_min`, 15) while the page is on, or on
demand. Every route: `409 disabled` when the page is off (except `GET`).

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/infra` | – | `{enabled, refreshing, error, refresh_min, generated_at, took_ms, harness_host, sources:{servers:{<name>:{ok, error, took_ms}}, cloudflare:{connected, key, error, sections:{zones, workers, worker_domains, pages, r2, d1, registrar, dns: "ok"\|"missing_permission"\|…}}, hostinger:{connected, key, sections:{domains, vps}}, vercel|netlify|supabase|github:{connected, key, error, label, beta, token_url, keys, sections:{sites, databases, buckets, functions, domains}}}, resources:[Resource], servers:[{name, label, host, user, port, note}]}` |
| POST | `/api/infra/refresh` | – | `{started, refreshing}` (`started:false` when one is already running) |
| POST | `/api/infra/annotate` | `{id, project?, note?, hidden?}` | the registry entry (`project:""` clears it) |
| GET | `/api/infra/reserved` | – | `{names}`: names a path site cannot take |
| POST | `/api/infra/servers/connect` | `{id: "server:hostinger:<n>", label?}` or `{host, user?, port?, label?}` | `{connected:true, name, label, host, user, port, via: existing_key\|added_key\|harness_key}`; `{connected:false, message, public_key, command}` when no key works on a non-Hostinger server; `409 exists`, `422 <code>` (`not_found`, `no_key`, `missing_permission`, `ssh_refused`…). A Hostinger VPS may get the Harness key in its root `authorized_keys` (the only provider write) and takes up to a minute |
| POST | `/api/infra/servers/rename` | `{name, label}` | `{name, label}` (the label shown; the name never changes) |
| POST | `/api/infra/servers/remove` | `{name}` | `{removed}`; `404` |
| POST | `/api/infra/domains` | `{name}` | `{name}` (normalised: lower case, IDNA, no scheme/path); `400 invalid_domain`. A domain from any registrar, read through RDAP + public DNS |
| POST | `/api/infra/domains/remove` | `{name}` | `{removed}`; `404` when it was not added by hand |
| GET | `/api/infra/mail?refresh=1` | – | Infra -> E-mail, view only (`infra/mailinfo.py`; `409 disabled` when the Infra page is off). `{generated_at, cached, mail_page, mailboxes:[{id, address, label, domain, imap_host, imap_port, smtp_host, smtp_port, has_password, last_check:{at, ok, error}\|null}], cloudflare:{connected, key, error?, message?, zones:[{zone, name, routing:{enabled, status}\|null, rules:[{name, enabled, catch_all, from, action: forward\|worker\|drop, to:[address], worker}], error?, missing_permission?}], addresses:[{email, verified, verified_at}], addresses_error?, addresses_fix?, missing_permission_zones?, fix?}, hostinger:{connected, key, error?, orders:[{id, domain, status, plan, seats, expires, mailboxes:[{address, status, catch_all}], aliases:[{address, to, enabled}], forwarders:[{from, to, enabled, confirmed, keep_copy}], catchalls:[{domain, to, enabled, confirmed}], error?}]}, routes:[{domain, address (`*@domain` = catch-all), via: cloudflare\|hostinger, kind: forward\|worker\|drop\|mailbox\|alias\|catchall\|other, enabled, account, worker, to:[{address, verified: bool\|null, account}]}], domains:[{domain, sources:[cloudflare\|hostinger\|mail_page], expects, checked, error, mx:[host], spf:{record, count, lookups}, dkim:[selector], dmarc:{record, count, policy}, problems:[{level: error\|warn\|info, code, text, fix, params}]}]}`. `account` = id of the E-mail page mailbox with that address. Provider calls are GET only, cached 5 min (`<state>/infra/mail.json`), DNS facts 1 h (`<state>/infra/mail-dns.json`, public DoH, `MAXXING_DOH_API`); `refresh=1` skips both. A provider error is in the payload, never a 5xx. Problem codes: `dns_unreachable, no_mail, null_mx, no_mx, mx_not_cloudflare, no_spf, multiple_spf, spf_all, spf_lookups, no_dkim, no_dmarc, multiple_dmarc, dmarc_no_policy, dmarc_none` |

Resource: `{id, kind: server|site|worker|pages|database|bucket|domain, name, location: local|<server>|cloudflare|hostinger|other,
provider, urls, status: ok|warn|down|unknown, status_detail (http_<code>, unreachable, timeout, tls_invalid, cert_expiring,
cert_expired, dns_elsewhere, domain_expiring, domain_expired, missing, disk_low, backup_failed, deploy_failed,
list_failed, file_missing, bad_probe), details, links:[id], project, note, hidden, declared, missing}`. Ids: `server:<name>`,
`site:<server>:<host><path>`, `db:<server>:<engine>:<container|native>:<db>`, `db:<server>:sqlite:<path>`,
`db:cloudflare:d1:<name>`, `bucket:<server>:garage:<name>`, `bucket:cloudflare:r2:<name>`, `worker:cloudflare:<name>`,
`pages:cloudflare:<name>`, `domain:<name>`, `server:hostinger:<id>` (a Hostinger VPS not registered for SSH).

## Mail

E-mail page (`maxxing/mail/`, Settings -> Features -> `mail_page`, off by default): any IMAP/SMTP mailbox, live (no
copy of the mail on the server). Every route answers `409 disabled` while the page is off. Accounts:
`<state>/mail/accounts.json` (no secret); each password is the vault key `MAIL_<ID>_PASSWORD`, never exposed to turns.
Errors `{error, message}`: `400 invalid`, `404 no_account|not_found|no_folder`, `409 exists|no_password`,
`413 too_large`, `422 refused` (every recipient refused) | `auth` (sign-in refused), `429 limit` (daily cap or more than 20 recipients),
`424 unreachable|tls|connection|imap|smtp` (the mail server failed; never a 5xx, which a proxy may replace by its own page),
`503 mail_busy` + `Retry-After` (another request holds that mailbox's IMAP connection for more than 30 s: a slow server).
Mail calls run on their own pool of 8 threads; a server that timed out is not tried again for 60 s (`unreachable` at once).

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/mail/accounts` | – | `[MailAccount]` `{id, label, address, name, username, imap_host, imap_port, imap_tls, smtp_host, smtp_port, smtp_tls, signature, password_key, has_password, created, smtp_checked, sent_today, send_per_day}` |
| POST | `/api/mail/detect` | `{address}` | `{source: known\|mx\|autoconfig\|guess, imap_*, smtp_*, mx}` (known providers, MX of the domain, Thunderbird's directory, else `mail.<domain>`) |
| POST | `/api/mail/accounts` | `{address, password, label?, name?, username?, imap_host, imap_port, imap_tls: ssl\|starttls\|none, smtp_host, smtp_port, smtp_tls, signature?}` | `{account, test: {imap, smtp, smtp_port, smtp_tls, smtp_changed, smtp_error?}}` (signs in first; SMTP 465 that does not answer -> 587 STARTTLS) |
| PATCH / DELETE | `/api/mail/accounts/{id}` | PATCH: same fields, all optional (`password` empty = kept) | `{account, test\|null}` / `{ok}` (DELETE removes the password from the vault, never the mailbox) |
| POST | `/api/mail/accounts/{id}/test` | – | `test` as above |
| GET / POST / PUT / DELETE | `/api/mail/{id}/folders` | POST `{name, parent?}`, PUT `{name, new_name}`, DELETE `?name=` | GET `[{name, role: inbox\|drafts\|sent\|archive\|junk\|trash\|all\|flagged\|null, delim, unread, total}]` |
| GET | `/api/mail/{id}/messages?folder=&page=&size=&q=&unread=&flagged=` | – | `{folder, total, exists, page, size, messages: [{uid, from, to, subject, date, seen, flagged, answered, size, attachments}]}` (newest first; `q` = server-side IMAP TEXT search) |
| GET | `/api/mail/{id}/message?folder=&uid=&seen=1` | – | `{uid, folder, from, to, cc, bcc, reply_to, subject, date, message_id, in_reply_to, references, text, html, remote_images, attachments: [{index, filename, content_type, size}], seen, flagged, answered}` (marks it read unless `seen=0`; `html` without scripts, `cid:` images inlined) |
| GET | `/api/mail/{id}/attachment?folder=&uid=&index=&inline=` | – | the file (`inline` only for images and PDF; `CSP: sandbox`) |
| POST | `/api/mail/{id}/actions` | `{folder, uids, action: seen\|unseen\|flag\|unflag\|move\|archive\|trash\|junk\|inbox\|delete, target?}` | `{ok, moved_to}` (`delete` only from trash / junk; an archive folder is created when missing) |
| GET | `/api/mail/{id}/compose?mode=reply\|replyall\|forward\|draft&folder=&uid=` | – | `{to, cc, bcc?, subject, text, in_reply_to, references, attachments}`: the fields a composer starts with (signature then quote for a reply, forwarded header + body, a draft as saved; never oneself in reply all) |
| POST | `/api/mail/{id}/send` | multipart: `data` = JSON `MailDraft` `{to, cc, bcc, subject, text, in_reply_to?, references?, reply?: {folder, uid}, forward?: {folder, uid, indexes}, draft?: {folder, uid}}`, `files` (≤ 30, ≤ 25 MB in total with the forwarded ones) | `{ok, message_id, recipients, refused, sent_folder}`: sent through the SMTP of the mailbox (plain text), copy filed in Sent (not for Gmail / Outlook, which do it), `reply` flagged answered, `draft` dropped. Capped: ≤ 20 recipients a message, `mail_send_per_day` (config, default 100) recipients a mailbox a day (`<state>/mail/sent-count.json`; a failed send gives them back) |
| POST | `/api/mail/{id}/draft` | as `/send` | `{folder, uid}`: filed in Drafts, replacing `draft` |
| POST | `/api/mail/refresh` | `{account?}` | `[{account, ok, error?, new, started}]`: check the mailbox(es) now (`mail/poll.py`); new mail starts the agents watching it |
| GET | `/api/mail/all?limit=100&before=` | – | `{messages: [{account, address, folder, uid, message_id, from, from_verified, subject, date, snippet, seen, attachments, seen_by}], checks: {<id>: {at, ok, error}}}`: the newest mail of every mailbox as the checks saw it (cache, not live) |
| GET | `/api/mail/outbox?account=` | – | `[{id, account, agent, agent_name, avatar, at, to, cc, bcc, subject, text, text_cut, files, draft: {folder, uid}, why, event_id, note}]`: messages written by agents waiting for the owner's OK |
| POST | `/api/mail/outbox/{id}/send\|deny` | – | `{id, status: sent\|refused}` (once; also the buttons of its Notifications event, ref `mailsend:<id>`); a text longer than the page shows (`text_cut`): 400 `too_long` (send it from its draft) |

Since the agents' e-mail (lot 2): `MailAccount` also has `poll_min` (5\|10\|30\|60 minutes between checks, default 10,
PATCH-able), `auth_servers` (host names whose `Authentication-Results` are trusted, set by the owner, PATCH-able),
`sender_check` (`{state: owner|auto|detected|none, server}`: who verifies the senders - the owner's servers, a known
provider found on nearly all recent mail and hosting the mailbox, a server found but not confirmed (the UI offers to
trust it = `auth_servers`), or nobody: then no sender is verified), `last_check` (`{at, ok, error}` or null), `agents` (the agents
that may use it: `{agent, name, avatar, enabled, rights, senders, approve_send, trigger}`) and `waiting` (outbox count).
List rows and `/message` have `from_verified` (the topmost `Authentication-Results`, written by the mailbox's provider,
says DMARC / DKIM / SPF passed for the sender's domain), `message_id`, and `seen_by`: `[{agent, at, what, detail, name,
avatar, exists}]` (`what`: seen, read, draft, filed, archived, replied, sent, marked read...; kept in `<state>/mail/mail.db`,
never written to the mailbox). An agent's `mail` setting (agent.json, `PATCH /api/agents/...` `{mail: [Grant]}`, 400
`bad_mail`): `Grant = {account, rights: [read, draft, move, mark, send], senders: ["*@example.com", "bob@example.com"],
approve_send: always|new|never, trigger: {enabled, folder, subject, senders, prompt} | null}`; enforced by `maxxing mail`
in the agent's turns (`mail/access.py`, `cmd_mail.Guard`).

## Team

Chats between people (`maxxing/team.py`, `maxxing/teampeer.py`, Settings -> Features -> `team_page`, off by default).
Errors: `{error, message}`: `400 empty|no_members|invalid_poll|invalid_emoji|bad_file|bad_id|bad_invitation|self|
not_https|not_public`, `404 not_found`, `409 nothing_new|not_reachable`, `502 summary_failed|unreachable|bad_answer`,
`504 timeout`.

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/team` | – | `{me, people:{<id>: Profile + {server, status, address?, peer?, contact?}}, chats:[Chat + {last, unread, updated}], reactions}` (a person's `photo_url`: `/api/team/people/{id}/photo?v=<version>`, `""` = none) |
| GET | `/api/team/people/{id}/photo?v=` | – | a contact's photo: fetched once per version from its server (signed GET `/api/team-peer/photo`, ≤ 512 KB, checked image and SHA-256), kept in `<state>/team/photos/`; `404` none / unreachable (asked again after 10 min) |
| POST | `/api/team/chats` | `{kind: dm\|group, members:[contact ids], name?, emoji?}` | Chat (a DM with the same person returns the existing one); a group is sent to every member with its pair keys |
| GET | `/api/team/chats/{cid}` | – | `{chat, messages:[Message]}` (format: `team.py` docstring) |
| POST | `/api/team/chats/{cid}/read` | – | `{ok}` |
| POST | `/api/team/chats/{cid}/messages` | `{text, reply_to?, files?:[{path}]}` | Message (`pending` = members not reached yet) |
| POST | `/api/team/chats/{cid}/messages/{mid}/edit` | `{text}` | Message (`edited`; own messages only) |
| POST | `/api/team/chats/{cid}/messages/{mid}/delete` | – | Message (`deleted`; own messages only) |
| POST | `/api/team/chats/{cid}/typing` | – | `{ok}` (signal to the members, at most every 3 s, never queued) |
| POST | `/api/team/chats/{cid}/group` | `{name?, emoji?, add?:[contact ids], remove?:[ids]}` | Chat (creator only) |
| POST | `/api/team/chats/{cid}/leave` | – | Chat (`left: "self"`, read-only, final) |
| POST | `/api/team/chats/{cid}/mute` | `{muted}` | Chat |
| POST | `/api/team/presence` | – | `{ok}` (the UI is open; sent to the contacts at most every 2 min) |
| POST | `/api/team/files` | multipart `file` (≤ `upload_max_mb`) | `{files:[{path, name, size, mime}]}` saved under `<workspace>/team/attachments/YYYY-MM/` |
| POST | `/api/team/chats/{cid}/messages/{mid}/react` | `{emoji}` | Message (toggle) |
| POST | `/api/team/chats/{cid}/polls` | `{question, options:[2..12], multi}` | Message |
| POST | `/api/team/chats/{cid}/messages/{mid}/vote` | `{option}` | Message (toggle; one answer clears the others unless `multi`) |
| POST | `/api/team/chats/{cid}/summarize` | `{ids?, since?}` | Message `kind: summary` (`ids` = the chosen messages, else after `since`, else after the last summary) |
| POST | `/api/team/chats/{cid}/messages/{mid}/forward` | `{text, session?}` or `{text, path, title?}` | `{session, message}`; the message's files go as attachments |
| GET | `/api/team/connections` | – | `{ok, address, reason: ""\|no_address\|not_https\|tailscale\|local, insecure, contacts:[{address, id, name, emoji, color, status: accepted\|request\|waiting, fingerprint, since, last_seen}], open_invites}` |
| POST | `/api/team/connections/invite` | – | `{invitation: "<address>#<code>", expires}` (15 min, one use) |
| POST | `/api/team/connections/join` | `{invitation}` | `{address, fingerprint}` (status `waiting` until the other side accepts) |
| POST | `/api/team/connections/answer` | `{address, accept}` | `{ok}` (accept is delivered at once, or fails) |
| POST | `/api/team/connections/remove` | `{address}` | `{ok}` (the other server is told) |

Between servers (public, no cookie, `404` while `team_page` is off; protocol in the `teampeer.py` docstring):

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/api/team-peer/hello` | `{from, to, nonce_b, proof, profile}` | `{nonce_a, proof_a, profile}` · `403` no matching invitation · `429` after 5 bad hellos/h/IP |
| POST | `/api/team-peer/inbox` | signed event `{type: accept\|refuse\|bye\|profile\|presence\|chat\|message\|vote\|react\|typing\|read\|edit\|delete\|leave, …}` | `{ok}` · `401` unsigned / stale / replayed · `403` bad signature · `429` `too_many_groups` (a new group past 50 open groups from that sender) |
| GET | `/api/team-peer/files/{fid}` | signed | the file, when the sender is a member of a chat where it was shared (`Content-Disposition` built by `downloads.content_disposition`) |
| GET | `/api/team-peer/photo` | signed (contact or group key, never a request not answered yet) | our profile photo (`image/jpeg\|png\|webp`, `nosniff`) · `404` none. The `profile` of hello / accept / profile / group rosters carries `photo` = its version (servers before 2.0.0a132 send none) |

## Dashboard & extensions
```
Card = {title?, status?:"ok"|"warn"|"error", link?:string, blocks:[Block], updated?:float}
Block =
  {type:"stat", label, value, hint?, delta?, tone?:"ok"|"warn"|"error"}
| {type:"stats", items:[stat…]}
| {type:"list", items:[{title, subtitle?, value?, href?, status?, icon?, emoji?}], empty?, grid?} (grid = tiles 2-3 per row; icon = lucide name drawn with the accent colour, preferred over emoji)
| {type:"chart", kind:"bar"|"line", series:[{name, points:[[x,y]]}], unit?}
| {type:"table", columns:[str], rows:[[cell]]}
| {type:"progress", label, value, max, hint?, unit?, format?:"percent"|"fraction"}
    // format "percent" -> "4.5 %" (value/max×100) · default "fraction" -> "2.3 / 16.4 GB" (unit appended)
| {type:"markdown", text}
| {type:"timeline", start, end, now?, more?, lanes:[{name, sub?, color?, href?, dense?, events:[{at, state?:"ok"|"error"|"running"|"planned", label?}]}]}
    // unix seconds; one row per lane: filled dot = ok/error, hollow = planned, pulsing = running, line = now.
    // dense: too many events to tell apart -> a band (only error/running dots drawn). A 24 h span is
    // labelled 00:00..24:00 from start (server time zone). Built-in "day" widget = today's crons.
```
| GET | `/api/dashboard` | – | `{widgets:[{id, title, icon, span:1\|2\|3, source:"builtin"\|"extension", card:Card\|null, error:string\|null, hidden:bool, pending?:true}]}` — hidden widgets are listed with `card:null` so the UI can show them again; a widget still computing after 1.5 s comes as `pending:true` (fetch it with the route below, which joins that computation); the `crons` and `day` cards are reused while jobs.json, runs.jsonl, the job locks and config.json are unchanged (10 s at most); `?force=1` recomputes everything |
| GET | `/api/dashboard/widgets/{id}?force=1` | – | one widget (refresh) |
| PUT | `/api/dashboard/layout` | `{order:[id], hidden:[id]}` | `{ok}` |
| GET | `/api/extensions` | – | `[{id, name, type:"widget"\|"page"\|"view", icon, version, enabled, error, has_api, pinned, page_v, agents_view}]` (pinned: page shown in the sidebar; page_v: page.js mtime in ms, the UI imports `page.js?v=<page_v>` so the module is reused until the file changes; agents_view: `{name, icon}` in the UI language when the extension brings an Office view of the Agents page and is not in error, else null) |
| PATCH | `/api/extensions/{id}` | `{enabled?, pinned?}` | `{ok}` (`pinned` on a widget -> 400 `not_a_page`) |
| PUT | `/api/extensions/pins` | `{order: [id]}` (≤ 200) | `{pinned: [id]}`: the pinned pages in their new sidebar order (the given ids first, then the pins it does not mention; an id that is not pinned is ignored: this never pins anything) |
| POST | `/api/extensions/reload` | – | rescans `<workspace>/extensions` |
| ANY | `/api/ext/{id}[/{path}]` | – | forwarded to the extension's `api.py` `handle()`: return value → JSON, `(status, body)` tuple sets the status, `ValueError` → 400, `LookupError` → 404, other → 500 `extension_error`, 30 s timeout (504 `extension_timeout`), 503 `extension_busy` at once while an earlier timed-out `handle()` of the same extension has not returned, or when the 4 extension threads are all still running earlier calls. A `.` / `..` segment in `path` → `400 bad_path` |
| GET | `/ext/{id}/page.js` | – | page module (ES module) |
| GET | `/ext/ui-kit.css` | – | the UI kit of extensions (`server/maxxing/assets/ui-kit.css`): `ui-*` classes scoped to `.mx-ext` (page host) and `[data-mx-kit]` (widget frame), built on the theme variables; the app adds it once when a page extension opens; `ETag` (content hash), `If-None-Match` -> `304` |
| GET | `/ext/{id}/widget-frame` | – | HTML widget document: the bridge (`maxxing.api / resize / theme`, theme from the URL fragment) + the UI kit inlined (`<html data-mx-kit>`) + `widget.html`, `Content-Security-Policy: sandbox allow-scripts allow-pointer-lock` (the UI frames it with the same sandbox; an srcdoc frame would inherit the app's script policy). `/ext/{id}/widget.html` stays the raw file (text/plain) |
| GET | `/ext/{id}/agents-view-frame` | – | an Office view of the Agents page: the same document as `widget-frame` (bridge, UI kit, CSP sandbox) with `agents-view.html`; 404 when the extension declares no `agents_view`, is off or in error. `/ext/{id}/agents-view.html` (GET, HEAD) = the raw file. The bridge also has `maxxing.data / onData / app / navigate`, answered only by the page that frames a view (web `HtmlWidget` `host`): pushed Office data, GET of `/api/agents/layout` only, routes under `/agents` only (checked on the resolved pathname) |

The app page (`index.html`) is served with `script-src 'self'` plus the hashes of its inline boot scripts
(`app._app_csp`): a page extension's `page.js` runs in the app, so it may not inject inline `<script>` nor use
`eval` / `new Function` (load code as modules from its own folder).

Extension folder: `<workspace>/extensions/<id>/manifest.json`
`{"id", "name", "type":"widget"|"page"|"view", "icon":"<lucide name>", "version", "span"?, "ttl"?: seconds, "agents_view"?: true | {"name"?: str | {lang: str}, "icon"?}}` +
`agents-view.html` (with `agents_view`; `type: "view"` = only that) +
`api.py` (widget: `def card(ctx) -> dict` returning a Card; page/API: `def handle(ctx, method, path, query, body) -> dict`) +
`page.js` (page: `export function mount(el, ctx) { …; return () => cleanup }`, `ctx = {api(path, opts), navigate, theme, lang, t, icon(name, {size?, className?}) -> <svg>}`).

Extension details: `ctx` (Python) = `{id, workspace, state_dir, secret(name) -> str|None, config:{timezone, language,
public_url}}`; `state_dir` = `<state>/extensions/<id>/` (created). Extensions are rescanned automatically when a
folder, `manifest.json`, `api.py` or `page.js` changes (hot reload). Widget ids of the built-ins (`activity, tasks,
crons, server, backup, telegram, usage`) are reserved. In `page.js`, `ctx.api(path, {method, body})` is expected to
call `/api/ext/<id>/<path>` with the CSRF header and resolve to the parsed JSON (see examples/extensions/notes-page).
Built-in card links are SPA routes: `/sessions/<id>`, `/sessions`, `/tasks?task=<id>`, `/crons?job=<id>`,
`/settings/{system,backup,telegram}`. Built-in card labels follow the configured language (en/fr).

## Memory

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/memory` | – | `{max_lines, files:[{path (workspace-relative), level:"global"\|"project"\|"topic", lines, bytes, over:bool}]}` |
| POST | `/api/memory/compact` | – | `{session: Session}` — a session at the workspace root runs the memory-compaction skill now with the line limit |

## Stats

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/stats/tokens?force=1` | – | `{totals, projects:[{name, …}], topics:[{path, label ("acme / blog", "acme / blog / Writer" for an agent folder), agent (display name or null), …}], sessions:[{id, title, path, archived, updated, …}] (top 100), days:[{date, tokens, cost_usd}] (90 days), latency:{start_s, first_answer_s, turns}, at}` (latency: medians over the last 20 turns of every session: seconds from starting `claude` to its first event / first answer); each group has `input, output, cache_read, cache_write, total, cost_usd, turns, sessions` (sorted by `total`; project `""` = workspace root). Cached 20 s |

## Feed (notifications)
`FeedEvent = {id, at, source, level: "info"|"success"|"warning"|"error", title, body, url, count, read, actions:
[{id, label, style: "primary"|"danger"|"default"|"link"}], ref, agent, resolved, resolution}` (`count` > 1 =
folded repeats). Kept 30 days in `<state>/feed.db`. **Alerts** = events with `actions` / `ref` (what they follow:
`approval:<request id>`, `health:<issue id>`, `agent:<path>#failed|budget|rate|trigger:<id>`, `agent:*#sandbox`) and
`agent` (the agent path, or null): `resolved` (time, null while open) + `resolution` ("Allowed", "Fixed"...) once their
cause is handled; their `actions` are then `[]`. `open` is a link button (the UI follows `url`); the others go to
`POST /api/feed/{id}/act/{action}`. Sources `agents` and `health` are built in.

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/feed?source=&unread=1&pending=1&before=<id>&limit=50` | – | `{events: FeedEvent[], more, unread, pending, sources: [{source, total, unread}]}` newest first (`limit` <= 200); `pending=1` = only the alerts still waiting (a request until decided, any other alert until read); `pending` = how many wait |
| POST | `/api/feed/{id}/act/{action}` | – | `{event}` after the action: `allow` / `deny` (an agent's request, as `POST /api/approvals/{id}`), `seen` (read; a health issue is marked seen), `open` (read). **Idempotent**: on a resolved event any action returns it unchanged (the same answer for a second click, web or Telegram) · `400 bad_action`, `404 not_found` |
| POST | `/api/feed` | `{title, body?, level?, source?, url?, dedupe?, group?}` | `{event, duplicate}` (`dedupe` = idempotent per source; `group` folds into the latest unread row of that group, 24 h) · `400 empty\|bad_level\|bad_source` |
| POST | `/api/feed/read` | `{ids?: number[], source?, all?: bool}` | `{unread}` |
| DELETE | `/api/feed/{id}` | – | `{ok}` |
| GET / PUT | `/api/feed/settings` | PUT `{telegram?: bool, health?: bool, rules?: {<source>: "auto"\|"off"\|"silent"\|"loud"}}` (merged; at most 200 non-auto rules, else `400 too_many_rules`) | `{telegram, health, sources: [{source, label, builtin, rule, own_thread}], hooks: FeedHook[], kinds, rules}`; `health` = config `health_feed` (server health problems as alerts; `maxxing init`: on for a new install, off for an older one) |
| POST | `/api/feed/hooks` | `{name, kind: "stripe"\|"shopify"\|"github"\|"generic", secret?}` | `FeedHook = {id, name, kind, created, url, has_secret}` · `409 exists\|reserved`, `400 bad_kind` |
| PATCH | `/api/feed/hooks/{id}` | `{secret?, regenerate?: bool}` | `FeedHook` (regenerate = new token, the old URL dies) |
| DELETE | `/api/feed/hooks/{id}` | – | `{ok}` |
| POST | `/api/feed/hooks/{id}/test` | – | `{event}` |
| POST | `/api/hooks/{token}` | the service's payload (<= 1 MB) | **public** (no cookie, no CSRF header: the token is the permission). Signatures: Stripe `Stripe-Signature` (5 min tolerance), Shopify `X-Shopify-Hmac-Sha256`, GitHub `X-Hub-Signature-256`, generic `X-Signature: sha256=<hex>` - checked when the hook has a secret; a stripe/shopify/github hook WITHOUT a secret refuses every delivery with `401 secret_required` (+ one folded `security` warning in the feed); a generic hook without a secret accepts the token alone. `200 {ok, duplicate, id}` / `{ok, ignored}` (a delivery verified with a secret whose body was already received is a duplicate whatever its unsigned headers, even if it was ignored or its event deleted: 30 days, generic 24 h; Shopify keys a known topic too) · `401 bad_signature\|secret_required`, `404` (unknown token: checked before the body is read), `413` (Content-Length or streamed body over 1 MB), `429` (120/min/hook), `400 bad_json` (also for JSON nested too deep), `400 bad_payload` (valid JSON whose fields have an unexpected shape for that service) |

Telegram: rule `auto` = error -> loud, warning -> silent, else off; built-in `crons`, `system`, `security` default to off
(own threads). The bot posts in the thread "Notifications" (`telegram.threads["#feed"]`) with buttons *Ask Claude*
(`callback_data f:<id>` -> new session in the default topic, event quoted as data) and *Open* (https links).

## Packs (starter projects)
`Pack = {id, project, emoji, icon, title, description, topics[], crons[] (names), installed, partial, project_exists, basics}` (title and
description in the configured language). Sources in `templates/packs/<id>/` (`pack.json` + `project/`). The first
pack is `basics` (`basics: true`, topics as `project/topic`): the default workspace from `templates/workspace/projects`.

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/packs` | - | `{packs: Pack[]}` |
| POST | `/api/packs/{id}/install` | - | `{ok, pack, project, created_files, jobs[]}` - adds the pack as a new project (`<project>`, or `<project>-2`, `-3`... when taken; its title lines renamed), sets the emoji, creates the pack's jobs disabled (`"<job> (<project>)"` for a copy). `basics`: copies the missing files of the default projects, `project` = `""`; `404 unknown_pack` |

## Skills
Read-only list of the skills Claude Code sees (Settings -> Skills, `maxxing/skills.py`): only the front matter of each
`<folder>/SKILL.md` is read (first 6 000 characters), nothing is written.
`Skill = {name, folder, description, origin, path, hidden, project?, topic?}`: `origin` = `product` (a shipped skill in
`<claude_dir>/skills`, rewritten by every update), `user` (the other folders there), `workspace` (`<workspace>/.claude/skills`),
`project` (`projects/<p>/.claude/skills`, with `project`), `topic` (`projects/<p>/topics/<t>/.claude/skills`, with `project`
and `topic`); `name` falls back to the folder; `hidden` = `disable-model-invocation: true`; `path` = the `SKILL.md`.

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/skills` | - | `{skills: Skill[]}` (product and user first, then workspace, then project by project, its topics after it) |

## Search

One SQLite FTS5 index (`<state>/search.db`, `maxxing/search.py`) over session messages, workspace text
files (`memory.md`/`CLAUDE.md` = kind `memory`; up to 256 KB each; vendored/build folders and data files -
.json, .csv, .tsv, .xml, .svg - skipped) and tasks. Every memory file of the root, the projects and the topics is
indexed (outside any cap); the other files get a fair budget per topic / project / root (`MAX_FILES` 20 000 //
buckets, clamped 50-1 000), each walk visits at most 20 000 entries and stops at its cap. Incremental: logs from
the last indexed offset, files on mtime/size change; refreshed every 30 s (sessions, memory files, tasks) with a
full walk of the other files every 10 min, and, for sessions, before each query. `GET /api/search/stats` adds
`files_walked_at` and `files` (last walk: files, buckets, per_bucket, cut, dropped). A refresh (or the hourly `optimize`) that changed rows ends
with `PRAGMA wal_checkpoint(TRUNCATE)` (200 ms busy timeout; retried next pass when a query holds a snapshot) and
`journal_size_limit` is 4 MB, so `search.db-wal` does not keep its high-water mark. After a files walk, at most once
a day, `search.db` is VACUUMed when more than 25 % of its pages are free (and it is at least 4 MB).

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/search?q=&kinds=session,file,memory,task,group&limit=30` | – | `{results:[{kind, id (session id / file path / task id / group path), path, title, snippet, at, score}], took_ms}` — every word required, as a prefix from 3 characters, accent-insensitive, BM25 (title x4; a session's title is on its title row only), one result per session/file/task (deduplicated in SQL), only the `RANK_MAX` (5 000) newest matching rows ranked, `cancelled: true` (no results) when the client went away; `group` = the conversations of the agent groups (`<state>/agents/rooms/*.jsonl`, a changed room indexed again whole, title row = the group's name, rows `@writer: …`), left out while Agents is off; `snippet` marks matches with `\u0002`…`\u0003` |
| GET | `/api/search/stats` | – | `{counts:{session, file, memory, task}, bytes, refreshed_at}` |
