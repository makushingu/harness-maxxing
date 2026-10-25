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
  in the temp dir (where the server spools uploads, often a small tmpfs) with min(`upload_min_free_mb`, 128 MB)
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
| PUT | `/api/auth/two-factor` | `{enabled}` | auth. `false`: off at once (trusted browsers forgotten) → `{ok, enabled:false}`. `true`: `409 not_linked` without a Telegram chat; already on → `{ok, enabled:true}`; else `{ok:false, two_factor:{challenge, expires_in}}`, on only once approved (poll `POST /two-factor`), this browser becomes trusted |
| POST | `/api/auth/two-factor/forget-browsers` | – | auth. New `device_key`: every trusted browser asks again, this one is re-trusted → `{ok}` |
| POST | `/api/auth/logout` | – | `{ok}` + cookie cleared. The cookie is also revoked server-side (`secrets.revoked_sessions`, kept until it would have expired): a copy of it is refused afterwards; other browsers stay signed in |
| POST | `/api/auth/password` | `{current, new}` | `{ok}` (min length 12, `security.MIN_PASSWORD`; `400 weak_password`, `400 bad_password` for a character UTF-8 cannot store, same on setup) + new cookie · wrong `current`: `401` after the sign-in delay, `429 throttled` past `FAIL_MAX` (own counter `pw:<client>`); rotates the cookie key: every other browser is signed out |

## Onboarding
| GET | `/api/onboarding` | – | `{completed, steps:{password:bool, claude:bool, workspace:bool, telegram:bool, backup:bool, profile:bool}}` (`profile` = the Profile step was answered, `register.asked`) |
| POST | `/api/onboarding/complete` | – | `{ok, jobs_enabled:[cron_id]}` (Claude signed in: the default jobs created off until then - Memory compaction - are turned on, once) |

## Claude
| GET | `/api/claude/status` | – | `{installed, version, auth:{ok, method:"oauth_token"\|"credentials"\|"api_key"\|null, detail, checked_at:float\|null, error:string\|null}, default_model, permission_mode, auto_compact_tokens, idle_compact_tokens, idle_compact_after_s, protect_secrets:bool, short_titles:bool, short_titles_model:bool, auto_update:{enabled:bool, checked_at:float\|null, latest:string\|null, last:{from, to, at:float, ok:bool, error:string\|null}\|null}, models:[{id,label,context_window:int\|null}]}` (`context_window`: as last reported by Claude Code on this server, null if never seen) |
| POST | `/api/claude/auth` | `{kind:"oauth_token"\|"api_key", value}` | stores the secret then runs a test call → `{ok, error?}` |
| DELETE | `/api/claude/auth` | – | removes stored token/key |
| POST | `/api/claude/test` | – | `{ok, model, ms, error?}` (real one-line call) |
| PUT | `/api/claude/settings` | `{default_model?, permission_mode?, auto_compact_tokens?, idle_compact_tokens?, idle_compact_after_s?, protect_secrets?, short_titles?, short_titles_model?, claude_auto_update?}` | `{ok}` · protect_secrets: deny rules on secrets.json and ~/.ssh for every turn · short_titles (default true): a session created with a message and no title gets a short title in the background, made locally, or by the smallest model with short_titles_model (default false) (INTERNALS.md `maxxing.sessions.titles`) · claude_auto_update (default false): the server runs `claude update` while idle, only for a release out for 2 days (INTERNALS.md#maxxingclaude_update) · permission_mode ∈ `bypass` (default) \| `acceptEdits` \| `default` · auto_compact_tokens: 0 = off, else a turn ending above it (at least 100 000) queues a summary turn + fresh thread (default 400 000) · idle_compact_tokens (0..2 000 000, default 200 000; 0 = off, else at least 20 000) / idle_compact_after_s (300..604 800, default 3600): a user message to a session idle for longer, with at least that context, is preceded by a summary turn and runs in the fresh thread |

`auth` reflects REAL calls, not the presence of a credentials file: the last session turn or test call with the
current method (success → `ok`, `checked_at`; a sign-in error such as "OAuth session expired…" or "Invalid API
key" → `ok:false`, `error`). A new `claude /login` (credentials file rewritten) or a new token clears an old
failure. With no recent result the server verifies in the background (`claude -p`, cheapest model, 60 s timeout)
at startup and at most every 6 h; a background timeout/network error does not mark the sign-in as failed.
`checked_at:null` = configured but not verified yet.

`models` = known ids (claude-opus-5-5, claude-sonnet-5-5, claude-haiku-4-5-20251001, claude-fable-5-1, …) + ids observed in logs.

## Workspace
| GET | `/api/workspace/tree` | – | `{root, projects:[Project]}` |
| POST | `/api/workspace/projects` | `{name, description?}` | `Project` (creates folder, CLAUDE.md, memory.md) |
| PATCH | `/api/workspace/projects/{project}` | `{name?, description?, emoji?}` | `Project` (rename moves the folder and remaps sessions; `emoji` = one emoji, `""` removes it, else `400 bad_emoji`; stored in `projects/<p>/.maxxing.json`) |
| PUT | `/api/workspace/order` | `{names: [project]}` | `{projects}` (tree order, stored in `projects/.order.json`; unlisted projects follow A-Z) |
| PUT | `/api/workspace/projects/{project}/order` | `{names: [topic]}` | `{topics}` (stored in `projects/<p>/.maxxing.json`) · `404` |
| DELETE | `/api/workspace/projects/{project}` | – | moves to trash · `409 has_running_sessions` |
| POST | `/api/workspace/projects/{project}/topics` | `{name, description?}` | `Topic` |
| PATCH / DELETE | `/api/workspace/projects/{project}/topics/{topic}` | `{name?, description?, permission_mode?}` | `Topic` · `permission_mode` ∈ `bypass` \| `acceptEdits` \| `default` \| `""` (the global setting), else `400 bad_permission_mode`; stored in `topics/<t>/.maxxing.json` |

```
Project = {name, path, description, topics:[Topic], session_count}
Topic   = {name, project, path, description, permission_mode:""|"bypass"|"acceptEdits"|"default", session_count, running:int, unread:int, telegram_thread:int|null}
```
Names: `^[a-z0-9][a-z0-9-]{0,47}$` (slug); the UI slugifies the label. Description goes into the CLAUDE.md header.

## Sessions
```
Session = {
  id, title, path,                    // topic path
  state: "idle"|"running"|"error",
  queue: int,                         // messages waiting
  queue_items: [{text, attachments: int, source: "web"|"telegram"|"cron"|"system", kind, voice?:true}],  // the waiting messages, in order (text cut at 280 chars): the queue stack shows them even when this tab did not queue them
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
  plan_ready: bool                    // a plan-mode turn finished OK: its plan waits for POST /plan/approve
}
```
| GET | `/api/sessions?path=&archived=0\|1` | – | `[Session]` sorted by `updated` desc (no path = all) |
| POST | `/api/sessions` | `{path, message?, title?, model?, attachments?:[filepath], plan_mode?:bool, voice?:filepath}` | `Session` (starts the first turn if message or voice) |
| GET | `/api/sessions/{id}` | – | `Session` |
| PATCH | `/api/sessions/{id}` | `{title?, model?, archived?, notify?, plan_mode?, favorite?, path?}` | `Session` (`plan_mode:false` also clears `plan_ready`; `favorite` is carried over by a hand-off; `path` moves the session to another topic and its Claude transcript with it - `400 bad_path`, `409 busy` while a turn runs or messages wait) |
| POST | `/api/sessions/{id}/plan/approve` | `{text?}` (shown in the thread as the user's message) | `{queued:bool, session:Session}` — plan mode off, then a turn that tells Claude to implement its latest plan (queue item flag `plan_approved`, kept by steer like `hud`) |
| DELETE | `/api/sessions/{id}` | – | `{ok}` (stops a running turn, moves the session to the trash) |
| POST | `/api/sessions/{id}/messages` | `{text, attachments?:[filepath], hud?:bool, voice?:filepath}` (`hud`: sent from the HUD - the prompt gets a short preface: answer short, annotate the screen capture if useful; `voice`: a voice message sent directly - uploaded first with `/api/uploads`, queued at once, transcribed by the server, then its transcript is the prompt) | `{queued:bool, session:Session}` · `409 voice_off` (transcription not ready) |
| DELETE | `/api/sessions/{id}/queue` | – | clears queued messages |
| POST | `/api/sessions/{id}/ask` | `{question}` | `{answer, cost_usd, duration_ms}` — side question: Claude answers from a throwaway copy of the session's thread (read-only, nothing saved: the running turn, queue and log are untouched). 409 `no_thread` (never answered yet) / `busy` (one already running for this session), 429 (2 running), 504 (240 s) |
| POST | `/api/sessions/{id}/queue/take` | – | `{messages:[{text, attachments}], session}` — removes the queued user messages and returns them (the composer's **Edit**: they come back in the composer and are sent again as a normal message) |
| POST | `/api/sessions/{id}/hide` | `{at, hidden=true}` | `{ok}` — hides (or shows again) the user message whose `at` is given: appends `{type:"mx_hide", ref, hidden}` to the raw log (nothing is erased; Claude's own thread is untouched), streamed as a `hide` event; 404 when no user message has that `at`, nothing written when it is already in that state. The UI offers it for a message whose turn ended without any answer (stopped) and drops that turn's rows |
| POST | `/api/sessions/{id}/steer` | – | `{steered:bool, interrupted:bool, session}` — while a turn runs: the queued user messages become ONE message (`steer: true`) at the head of the queue and the runner gets SIGUSR1: it ends the current turn (only that one: meta `steer_turn` = `turn_id`) and runs that message next in the same Claude thread, prefaced so Claude continues the task with it. A compact / handoff turn is not interrupted (`interrupted:false`, the message runs right after it). `steered:false` when idle or nothing is queued |
| POST | `/api/sessions/{id}/stop` | – | `{ok}` (clears the queue, aborts the running turn; returns once settled, ≤ ~10 s). During an idle-compaction summary only the summary is aborted: the message waiting behind it (queue item `held`) stays and runs |
| POST | `/api/sessions/{id}/compact` | – | `{ok}` summary → fresh Claude context, same session · `409 busy` while running · `400 empty_session` |
| POST | `/api/sessions/{id}/handoff` | – | `Session` (new session seeded with a summary; old one archived). Messages sent to the new session before the summary arrives are queued (`queued:true`) and run after the seed (10 min at most, or at once when the summary fails) |
| POST | `/api/sessions/{id}/seen` | – | `{ok}` |
| GET | `/api/sessions/{id}/events?tail=N` | – | last events, read backwards from the end (whole log lines, at least N events when available, max 5000): `{events, start, next, more_before:bool, state}` — `start` = offset of the first line returned, `next` = end offset (start the stream there). What the UI uses to open a thread |
| GET | `/api/sessions/{id}/events?before=<offset>&limit=N` | – | events strictly before `offset` (backward paging, "Show earlier messages"): `{events, start, next:offset, more_before, state}` · `{events:[], reset:true, state}` when `offset` is not a line boundary of the current log |
| GET | `/api/sessions/{id}/events?from=0` | – | forward reading `{events:[Event], next:int, state, more:bool}` (≤ 4 MB of log per call; `more` = call again from `next`) · `reset:true` when `from` is beyond the end / not a line boundary |
| GET | `/api/sessions/{id}/stream?from=0` | – | **SSE**. `event: events` `data: {events, next}` · `event: state` `data: Session` · `event: reset` `data: {}` then end of stream when the log was rewritten or shrank (or `from` is stale): reload with `?tail=` · heartbeat comment every 15 s |
| GET | `/api/sessions/search?q=` | – | `[{id, title, path, snippet, at}]` (served by the full-text index, see Search; max 50) |
| POST | `/api/uploads?path=<topic path>` | multipart `file` (multi) | `{files:[{path, name, size, mime}]}` saved in `<topic>/attachments/YYYY-MM/` · each file `413 too_large` over `upload_max_mb`, `507 disk_full` when it would leave less than `upload_min_free_mb` free on the destination disk (files saved before it in the same request are kept); the whole request is capped too (see Conventions) |

`from`/`next`/`start`/`before` = byte offsets in the raw log (always line boundaries). Backward reads scan at
most 64 MB per call (then `more_before` with the `start` reached). The runner clips tool outputs before
writing them (2 000 characters per tool result, images → `[image]`, Write/Edit inputs beyond 20 kB; the block
gets `mx_clipped`), keeps only `cwd, session_id, model, permissionMode, apiKeySource, claude_code_version,
output_style, fast_mode_state, mcp_servers, uuid` of `system/init` lines (the tool / skill / slash-command
lists, ~20 kB per turn, are dropped) and does not write `system/thinking_tokens` lines; `maxxing sessions
compact-logs [--dry-run]` applies the same to existing logs (atomic
rewrite, running sessions skipped) — open streams then receive `reset`. **Event** (normalised):
```
{type:"user", text, attachments:[path], at, source, voice?:[path]}   // voice: a voice message sent directly (its audio)
{type:"voice_text", text, error:str|null, stopped?:true, at}   // transcript of the voice message just above (error: not transcribed, nothing sent to Claude)
{type:"assistant", text, at}                       // markdown
{type:"thinking", text, at}
{type:"tool_use", id, name, input, summary, at}     // summary = one-line human string ("Read src/app.py", "Bash: ls -la")
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
| GET | `/api/files/raw?path=&download=0&v=` | – | bytes, Range supported (video). Every type but images (not SVG), audio, video and PDF gets `Content-Security-Policy: sandbox; default-src 'none'; …` (+ `nosniff` always). `v` (the file's mtime, set by the UI when it knows it) = cached by the browser for good, else `no-cache` + ETag. |
| GET | `/api/files/thumb?path=&w=320&v=` | – | webp thumbnail for images, videos and PDFs (ffmpeg, video: frame at 1 s; PDF: first page through `pdftoppm`), cached server side; without ffmpeg images fall back to the original · other types `415`. `w` ≤ 4096. Cache: `no-cache` (revalidated), or for good with `v`. Same CSP rule as `/raw` (an SVG fallback is sandboxed) |
| POST | `/api/files/stat` | `{paths: [str]}` (≤ 500) | `{mtimes: {path: float \| null}}` - current mtime of each file (null = missing, outside the files root, not absolute). The UI puts it in preview URLs (`v`) so a file rewritten under the same name shows its new version |
| GET | `/api/files/video?path=` | – | `{width, height, codec, bitrate, duration, fps, qualities: [{q, state: none\|queued\|running\|ready\|error, progress 0-1, error?}], auto}`: the lighter copies offered (1080 / 720 / 480 below the original's height) and the copy "Auto" plays (`null` = the original: H.264 / VP8 / VP9, ≤ 1080p, ≤ 6 Mbit/s) · not a video `415` · no ffprobe / no video stream `422 video_unavailable` |
| POST | `/api/files/video/prepare` | `{path, q}` | queues the copy at height `q` (H.264 crf 23 veryfast + AAC 128k, maxrate 5M / 2.5M / 1.2M, `+faststart`, `nice 10`, 2 threads, one encode at a time) in `<state>/videos/<sha1(path, mtime, size)>-<q>.mp4`; no-op when ready or queued; returns the same as GET · `q` not offered or no ffmpeg `422`. Poll GET for progress |
| GET | `/api/files/video/stream?path=&q=&v=` | – | the ready copy (`video/mp4`, Range requests) · not made yet `404 not_ready`. Touches the file: past 4 GB (`VIDEO_CACHE_MAX`) the least recently played copies are removed after each encode |
| GET | `/api/files/preview?path=&w=2048&v=` | – | the image the viewer shows: a WebP at most `w` px wide (cached server side) when the original is over 300 KB, else the original (GIF / SVG always original; TIFF / HEIC always converted, `415` when the server cannot) · not an image `415` |
| GET | `/api/files/archive?path=` | – | `{path, format:"zip"\|"tar"\|"gzip", entries:[{name, size, dir, mtime}], count, total_size, truncated, size}` (first 5000 entries, nothing extracted; a tar is read through 256 MB decompressed and 3 s at most, a zip directory 3 s, then `truncated` with the counts so far; cached per file version) · other formats / unreadable `415 unsupported` |
| GET | `/api/files/site-url?path=` | – | `{url, expires_in}`: `/api/files/site/<token>/<name>` renders an HTML file (`.html`/`.htm` only, 415 otherwise) with its relative assets for 2 h. Folder token: only static web assets of the page's folder tree (`html htm css js mjs wasm`, fonts `woff woff2 ttf otf eot`, pictures, audio, video; never `.md .json .txt .csv .pdf .xml`, code or settings); from a topic's `attachments/`, pictures and media only. When the page's folder is the files root, the home directory, `/`, under a dot folder, the workspace root, `projects/`, a project, its `topics/` or a topic's `attachments/`, the token covers that file only (never under a dot folder). The token carries its issue time and session id: refused after that session signs out, when it is older than `sessions_not_before`, or after a password change |
| GET | `/api/files/site/<token>/<rel path>` | – (**no cookie**: the token, scoped to the page's folder, is the permission) | the file, with `Content-Security-Policy: sandbox allow-scripts allow-popups allow-forms allow-modals allow-downloads` (no `allow-same-origin`: opaque origin, no session; no `allow-popups-to-escape-sandbox`: popups and `target=_blank` links inherit the sandbox; the UI iframe uses the same flags) + `frame-ancestors 'self'`; outside the folder, any dotfile / dot folder in the path, another file of a single-file token, or a file type outside the list above `403`; expired, revoked / forged token `403 expired` |
| PUT | `/api/files/write` | `{path, content, expected_mtime?}` | `{ok, mtime}` · `409 conflict` when mtime differs |
| POST | `/api/files/mkdir` | `{path}` | `{ok}` · `409 exists` when something (a file, a dangling link) is already there or a file is in the way |
| POST | `/api/files/move` | `{from, to}` | `{ok}` · moving the workspace or a folder holding it `403 forbidden`; a folder with a running session in it `409 has_running_sessions` (same rule as the workspace API) |
| POST | `/api/files/delete` | `{path}` | `{ok}` (to trash) · same `403` / `409 has_running_sessions` rules as `move` |
| POST | `/api/files/upload?dir=` | multipart | `{files:[…]}` · same limits as `/api/uploads` (`413 too_large`, `507 disk_full`) |
| GET | `/api/files/search?q=` | – | `[{path, name, type}]` (workspace, max 50) |

## Trash
Everything deleted (files, folders, topics and projects with their sessions, single sessions) lands in
`state_dir("trash")`; items older than 30 days are hidden from the list and purged when the trash is listed (at most once an hour).
| GET | `/api/trash` | – | `{items:[{id, kind:"file"\|"folder"\|"topic"\|"project"\|"session"\|"previous_versions", name, original, at, size, sessions:int, restorable}], keep_days}` newest first (`original` workspace-relative; for a session: its topic path) |
| POST | `/api/trash/{id}/restore` | – | back where it was - a free name next to it if the place is taken (`<name> (restored).ext`, topics/projects `<name>-restored`, `<name>-restored-2`…, the name cut so the result stays a valid name of at most 48 characters); sessions come back with their topic (a session whose topic is gone comes back at the workspace root) → `{ok, kind, restored_to, sessions}` · `404 not_found` · `409 not_restorable` (backup "previous versions") |
| DELETE | `/api/trash/{id}` | – | deletes one item forever → `{ok}` |
| DELETE | `/api/trash` | – | empties the trash → `{ok, deleted}` |

## Tasks (`<workspace>/tasks.json`)
```
Task    = {id, title, notes, status:"todo"|"doing"|"done", priority:0|1|2|3, due:"YYYY-MM-DD"|null,
           project_id|null, topic_path|null, labels:[str], created, updated, done_at|null, order:float}
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
| POST | `/api/tasks` | partial Task (title required) | `Task` |
| PATCH | `/api/tasks/{id}` | partial Task | `Task` |
| DELETE | `/api/tasks/{id}` | – | `{ok}` |
| POST | `/api/tasks/bulk` | `{ids:[id], patch?:{status?, priority?, project_id?, due?, topic_path?, labels?}, labels_add?:[str], labels_remove?:[str], delete?:bool}` | `{ok, updated, deleted}` — one atomic write; unknown ids ignored (max 1000); tasks entering a column keep their relative order (top of `done`, bottom elsewhere) · `400 invalid_ids`/validation codes of PATCH |
| POST / PATCH / DELETE | `/api/tasks/projects[/{id}]` | `{name, color, hidden?}` | `TaskProject` · DELETE `409 linked_project` |

## Crons
```
Cron = {id, name, schedule,            // 5-field cron expression
        kind:"shell"|"claude", command, // shell
        topic_path, prompt, model, reuse_session:bool,  // claude
        permission_mode:""|"bypass"|"acceptEdits"|"default",  // claude; "" = the topic's, else the global mode
        enabled, notify:"never"|"failure"|"always", timeout_s,
        last_run:{at, ok, code, duration_s}|null, next_run:float|null, human:string,
        running:bool}                  // a run is in progress (flock held); overlapping runs are skipped
Run  = {id, cron_id, name, at, ok, code, duration_s, output_tail, session_id|null}
```
| GET | `/api/crons` | – | `{jobs:[Cron], external:[{schedule, command, human}]}` (external = crontab lines outside the managed block, read-only) |
| POST | `/api/crons` | Cron fields | `Cron` (validates expression; syncs crontab) |
| PATCH / DELETE | `/api/crons/{id}` | | |
| POST | `/api/crons/{id}/run` | – | `{ok}` (runs now in a transient unit) · `409 already_running` |
| GET | `/api/crons/runs?cron_id=&limit=50` | – | `[Run]` |
| GET | `/api/crons/{id}` | – | `Cron` |
| GET | `/api/crons/preview?schedule=` | – | `{valid, human, next:[at×5], error?}` (next runs in the configured time zone) |

## Telegram
| GET | `/api/telegram` | – | `{configured, running, bot:{id, username, name}\|null, chat:{id, title, type}\|null, topics_enabled, threads:[{path, thread_id, name, session_id?}], settings:{notify_crons, login_alerts, two_factor:bool, reply_mode:"progress"(default)\|"final", thread_days:int(30), mirror_web:bool(false)}, linking:bool, last_error}` (special threads: path `"#crons"` / `"#alerts"`; session threads: `session_id`, path `""`) |
| POST | `/api/telegram/token` | `{token}` | getMe → `{ok, bot}` · `400 bad_token` (bad format, rejected, or bot already bound to a webhook). A different bot resets the chat link |
| POST | `/api/telegram/link` | – | `{code, deep_link}` (`https://t.me/<bot>?start=<code>`, valid 15 min) — starts polling and waits for `/start <code>` from a private chat; threads are synced right after linking · `409 not_configured` |
| GET | `/api/telegram/link` | – | `{linked, chat}` |
| POST | `/api/telegram/sync` | – | makes the threads match: "Crons" + "Alerts" + one per open session (human, not archived, active in the last `thread_days` days, ≤ 50; created / renamed / deleted; a thread found deleted - on a send or a rename - is reopened for its session; Telegram has no silent check, so threads are not probed) → `{created:int, deleted:int, topics_enabled:bool, error:string\|null}` (topics disabled for the bot → `topics_enabled:false`, everything goes to the main chat). Also automatic: a few seconds after any session change and every 10 min |
| PUT | `/api/telegram/settings` | partial settings (`thread_days` 1–365) | `{ok}` |
| POST | `/api/telegram/test` | – | sends a test message → `{ok}` · `409 not_linked` · `502 telegram_error` |
| DELETE | `/api/telegram` | – | unlink + forget token, threads and the Telegram sessions map |

## Backup
| GET | `/api/backup` | – | `{configured, repo, private:bool\|null, schedule, include:[glob], always:[glob], last:{at, ok, commit, files, error}\|null}` (`always` = CLAUDE.md/memory.md globs, always included) |
| POST | `/api/backup/config` | `{repo:"owner/name", token, create?:bool}` | verifies access/private/push (creates the private repo if asked; token may be omitted to keep the stored one) → `{ok, private, created?, warning?, error?}`; on success creates/updates the "Memory backup" cron job; `ok:false` while a backup or restore runs |
| PUT | `/api/backup/settings` | `{schedule?, include?}` | `{ok}` |
| POST | `/api/backup/run` | – | `{ok, commit, files, changed?, error?, code?, leaks?:[{file, kinds}]}` (`code`: `secret_found`, `public_repo`, `not_configured`, `git_failed`…; `409 busy`) |
| GET | `/api/backup/history?limit=100` | – | `[{at, ok, commit, files, changed, error, code?, duration_s}]` newest first |
| POST | `/api/backup/restore` | `{ref?}` | restores whitelisted files (current files saved to trash first) + cron jobs + server-independent settings → `{ok, files, restored:[path], unchanged, skipped:[path], crons:bool, mcp:int, held:{crons, extensions, hooks, mcp, review, outside?}, trash}` (local MCP servers and new jobs/extension code are held, see Backup docs) · `409 not_configured\|empty\|busy` |
| DELETE | `/api/backup` | – | forget repo + token (`409 busy` while a backup or restore runs) |

## Settings & secrets
| GET / PUT | `/api/settings` | `{timezone, language:"en"\|"fr", public_url, files_root, presentation_default?, usage_widget:bool, git_page:bool, infra_page:bool, maxxing_mode:bool, memory_max_lines:int, result_line_hidden:["model"\|"duration"\|"cost"\|"tokens"\|"cache"], donation_hidden:bool}` (`donation_hidden`: hides the donation links of What's new, Feedback and Settings -> License for every browser, default false; Settings -> Support stays) (`result_line_hidden`: parts of the line under each answer that are hidden, default `[]`, unknown values = 422, stored in canonical order) (`git_page`: the Git page `/git` and its sidebar entry, default false) (`maxxing_mode`: beta, Maxxing mode of the Sessions page - its switch, meter, driver and Alt+M -, default false) (`memory_max_lines`: 0 = no limit, else 50-5000, default 200) — a new `timezone` also switches the server zone (`timedatectl`, cron restarted) |
| PUT | `/api/settings/look` | `{theme:"dark"\|"light"\|"system", accent:"blue"\|"clay"\|"violet"\|"green"\|"amber"\|"rose", tint?:"neutral"\|"tinted"}` | `{ok, look}` · sent by the web app 600 ms after a change of theme / accent / tint (config `look`) · `422` bad value |
| GET / PUT | `/api/settings/profile` | `{name ≤32, color: "clay"\|"blue"\|"violet"\|"green"\|"amber"\|"rose"\|"teal"\|"zinc", emoji}` | `Profile` (bus `profile`) |
| GET / PUT | `/api/settings/register` | `{count?, email?, news?, asked?}` (email: valid or `""`) | `RegisterState` `{count, count_blocked, email, news, asked, registered, error, synced_at}` (bus `register`). Optional hello to the authors (`maxxing/register.py`): `count` (default `true`) = anonymous daily signal (cloud id + version + `os`, `arch`, `health` codes), `count_blocked` = `MAXXING_NO_TELEMETRY` / `DO_NOT_TRACK` set in the service environment (counter off whatever `count`); `email` (+ `news`) adds pseudo and language; neither = cloud row archived (kept, never contacted again). An update never turns on the email or the news; 2.0.0a94 turned `count` on once where `asked` was false. |
| GET / POST | `/api/settings/feedback` | POST `{email, type: bug\|idea\|other, message}` | GET `{email, version}` (prefill); POST `{ok}`. Feedback to the authors (`maxxing/feedback.py` -> cloud `/v1/feedback`). Errors: 400 `invalid_email` / `message_required` / `too_long` / cloud codes, 429 `rate`, 502 `unreachable`, 503 `offline`. |
| GET / PUT / DELETE | `/api/settings/license` | PUT `{key}` (`HM-XXXX-XXXX-XXXX-XXXX`) | `{has_key, key_hint, kind, email, max_servers, expires_at, activated_at, enabled, moved_to_git}` (bus `license`, never the key). Optional Enterprise key: PUT = `license.activate` (cloud `/v1/activate`: checks it, counts this server; 400 `invalid_key` / `limit` / `revoked` / `expired` with the cloud message), DELETE = `remove_key` (frees the seat). Changes nothing else: code and updates stay on git. |
| GET | `/api/secrets` | – | `[{name, note, expose, updated, preview}]` (preview = first 4 chars + …, only `…` for values < 8 chars) |
| PUT | `/api/secrets/{name}` | `{value?, note?, expose?}` | `{ok}` · `400 invalid_name\|reserved_name\|value_required` (PATH, HOME…, MAXXING_* are reserved) — `expose` = exported as env var to Claude sessions |
| GET | `/api/secrets/{name}/reveal` | – | `{value}` |
| DELETE | `/api/secrets/{name}` | – | `{ok}` |

## MCP servers
Claude Code's MCP servers (maxxing/mcp.py), shown in Settings -> MCP. Bus topic `mcp`.
```
McpServer = {id:"<scope>|<folder>|<name>", name, scope:"user"|"local"|"project",
  where:{rel:"projects/acme/topics/ads"|null, project, topic, exists, path:"/abs/folder"|null},
  type:"http"|"sse"|"stdio", url?, command?, args?, headers?, env?,   (secrets shown as "•••": every header / env
    value that is not only ${KEY} references (an auth scheme word aside; Content-Type, Accept... stay), the
    user:password and query values of url)
  literal_secret:bool, keys:[vault names referenced as ${KEY}],
  state:"connected"|"needs_auth"|"failed"|"pending"|"unknown", detail, checked_at, approved? (project scope)}
```
| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/mcp` | – | `{servers:[McpServer], checking, checked_at, config_file}` (first call starts a check) |
| POST | `/api/mcp/check` | – | `{checking:true}` - `claude mcp list` per folder in the background, then bus `mcp` |
| POST | `/api/mcp` | `{name, where:"" \| "projects/…", type:"http"\|"sse"\|"stdio", url?, command?, args?, headers?, env?}` | `{id, exposed:[vault keys now exposed]}` · `400 bad_name\|bad_url\|bad_command\|bad_type\|bad_where`, `404 folder_missing`, `409 exists` |
| DELETE | `/api/mcp?id=` | – | `{ok}` |
| POST | `/api/mcp/login` | `{id}` | `{login, url}` - runs `claude mcp login --no-browser` in a pseudo-terminal; replaces an attempt already open for that server · `400 no_login_url`, `404 folder_missing`, `500 no_claude\|cli_failed` |
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
| GET | `/api/pc/download/{target}?code=` | – | the agent binary + config trailer · public, `403`, `404` |
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

Telegram: voice notes, audio files and video notes in a session thread are downloaded, transcribed, echoed as
`🎤 <transcript>` and sent to the session as the user message (attachment = the audio file). Engine off → a hint.

## System
| GET | `/api/system/health` | – | `{ok, issues:[{level, code, text}], cpu_pct, load, mem:{total,avail}, disk:{total,free,pct}, uptime_s, claude_auth, claude_auth_error, claude_checked_at, backup_age_h, failed_logins_1h, at}` (each issue also has `id` and `seen`; issue `claude_auth`: "Claude is not connected" or "Claude sign-in expired…") (cached 30 s, `?force=1`) |
| POST | `/api/system/health/seen` | `{id, seen=true}` | the health above, fresh - marks a current issue as seen (or not): it stops counting in the sidebar dot until its text changes (numbers left out of the `id`) or for 24 h; marks in `<state>/health-seen.json` · `404 not_found` |
| GET | `/api/system/services` | – | `[{name, label, active:bool, enabled:bool, since:float\|null, state}]` (claude-maxxing, caddy, tailscaled, cron + config `services_extra`; units not installed are omitted; one `systemctl show` call, cached 10 s, dropped by a service action) |
| POST | `/api/system/services/{name}/{start\|stop\|restart}` | – | `{ok}` (self restart deferred 2 s) |
| GET | `/api/system/logs?unit=&lines=200` | – | `{lines:[str]}` |
| GET | `/api/system/version?refresh=1` | – | `{version, commit, latest_commit\|null, behind:int\|null, checking:bool, checked_at:float\|null, custom:{count, titles, dirty, rebase}, pending:{at, reason:"conflict"\|"health"\|"dependencies", target_version?, conflicts?}\|null, license:{enabled, key_hint, email, kind, updates_until, expires_at, channel, latest, message, max_servers, moved_to_git, move_error}, report:{at, version, ok, problems}\|null, after:{to, at, notes_session?, notes_path?, done}\|null}` (remote checked every 10 min with git and the update token; nothing on an install still on archives until it has moved to git; `refresh=1` checks now and waits; `commit` and `custom` count/titles/dirty are cached 30 s and while the clone's HEAD / branch ref / index are unchanged, `refresh=1` re-reads them, `rebase` and `pending` are always fresh) |
| POST | `/api/system/update` | – | `{ok}` starts `maxxing update --smart` in a transient unit (after the restart the server verifies, then opens the upgrade-notes session) |
| GET | `/api/system/update/preflight?refresh=` | – | `Preflight` = `{ok, verdict: up_to_date\|simple\|adapt, current, latest, behind, customs:[{id, title, why, files, status: ok\|review\|included\|conflict\|unknown, conflicts, overlap}], unsaved, unsaved_overlap?, web_changes, extensions:[{id, name, api, reason}], notes:[{version}], changelog}` - the update simulated in a throw-away git worktree; cached until HEAD / target / unsaved files change; `refresh` fetches first · `502 preflight_failed` |
| POST | `/api/system/update/assist` | – | `{session}`: a session in the update topic that adapts this server's changes then updates |
| GET | `/api/system/update/report` | – | `{report}` = last verification `{at, version, ok, problems, extensions:[{id, name, type, ok, error, skipped?}], checks:[{id, title, check, ok, output}]}` or null |
| POST | `/api/system/update/verify` | – | `{report}`: verify now |
| POST | `/api/system/update/fix` | – | `{session}`: a session that fixes what the last report found · `409 nothing_to_fix` |
| GET | `/api/system/changelog?limit=10` | – | `{version, entries:[{version, label, current:bool, body:markdown}]}` newest first, parsed from the public `CHANGELOG.md` (`2.0.0-alpha.6` matches `2.0.0a6`); `limit` 1-500 (Settings -> Updates asks 500) |
| GET | `/api/usage` | – | experimental Claude plan usage `{available, five_hour:{pct, resets_at}\|null, seven_day:{…}\|null, reason?, stale?, retry_at?}` (off unless settings `usage_widget`; 60 s cache, `?force=1`). Token: the stored long-lived `claude_oauth_token` first, else the `claude login` credentials file. `reason`: `disabled`, `no_oauth_credentials`, `api_key` (no plan usage with an API key), `rate_limited` (429: no call before `retry_at` = now + Retry-After, even forced; the last good values are returned with `stale`), `http_<status>`, or an exception name |

## Import (from another agent)
Zip layout and merge rules: `server/maxxing/importer.py` and docs/user/21-import.md.
| GET | `/api/import/prompt?agent=hermes\|claude-code\|openclaw\|other` | – | `{agent, agents, prompt}` |
| POST | `/api/import/upload` | multipart `file` (≤ 600 MB) | preview, writes nothing → `{id, name, projects:[{name, exists, topics:[{name, source, files, exists}]}], skills, aside, root_memory, files, size, skipped:[{file, reason}], secrets:[{file, kinds}], renamed:[{from, to}]}` · `400 bad_zip\|empty` · `413 too_big\|too_many_files` |
| POST | `/api/import/{id}/apply` | – | imports (never overwrites: memory/CLAUDE.md get an "## Imported" section, other files `<name> (imported)`, skills `<name>-imported`; files with secrets refused; Claude Code settings and Harness folder settings `.maxxing.json` / `.order.json` refused; a file whose place is taken by a folder, sits behind a file, or would be written through a link leading out of the workspace is added to `skipped` and the import goes on) → `{ok, projects, topics, files, merged, renamed, skills, aside, secrets, skipped, folder, report, finish_prompt}` · `404 not_found` (expired, 24 h) |
| DELETE | `/api/import/{id}` | – | forgets an upload → `{ok}` |

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
| GET | `/api/git/graph?repo=&limit=200&branches=a,b` | – | `{repo:{kind: local\|github, id, name, branch, github, ...summary or {url, private, permission, description, branches, branches_shown}}, commits:[{sha, parents, refs:[{name, kind: head\|branch\|remote\|tag, current?}], author, date, subject}], truncated}` — newest first, children before parents; limit ≤ 1000; GitHub = default branch (100) + the 12 other branches (40 each) merged |
| GET | `/api/git/commit?repo=&sha=` | – | `{sha, parents, author, email, date, message, files:[{path, additions, deletions}], files_total, url?}` (a merge: diff against its first parent; ≤ 300 files; an annotated tag shows its commit; 404 `no_commit` for a tree or blob id) |
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

Resource: `{id, kind: server|site|worker|pages|database|bucket|domain, name, location: local|<server>|cloudflare|hostinger|other,
provider, urls, status: ok|warn|down|unknown, status_detail (http_<code>, unreachable, timeout, tls_invalid, cert_expiring,
cert_expired, dns_elsewhere, domain_expiring, domain_expired, missing, disk_low, backup_failed, deploy_failed,
list_failed, file_missing), details, links:[id], project, note, hidden, declared, missing}`. Ids: `server:<name>`,
`site:<server>:<host><path>`, `db:<server>:<engine>:<container|native>:<db>`, `db:<server>:sqlite:<path>`,
`db:cloudflare:d1:<name>`, `bucket:<server>:garage:<name>`, `bucket:cloudflare:r2:<name>`, `worker:cloudflare:<name>`,
`pages:cloudflare:<name>`, `domain:<name>`, `server:hostinger:<id>` (a Hostinger VPS not registered for SSH).

## Team

Chats between people (`maxxing/team.py`, `maxxing/teampeer.py`, Settings -> Features -> `team_page`, off by default).
Errors: `{error, message}`: `400 empty|no_members|invalid_poll|invalid_emoji|bad_file|bad_id|bad_invitation|self|
not_https|not_public`, `404 not_found`, `409 nothing_new|not_reachable`, `502 summary_failed|unreachable|bad_answer`,
`504 timeout`.

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/team` | – | `{me, people:{<id>: Profile + {server, status, address?, peer?, contact?}}, chats:[Chat + {last, unread, updated}], reactions}` |
| POST | `/api/team/chats` | `{kind: dm\|group, members:[contact ids], name?, emoji?}` | Chat (a DM with the same person returns the existing one); a group is sent to every member with its pair keys |
| GET | `/api/team/chats/{cid}` | – | `{chat, messages:[Message]}` (format: `team.py` docstring) |
| POST | `/api/team/chats/{cid}/read` | – | `{ok}` |
| POST | `/api/team/chats/{cid}/messages` | `{text, reply_to?, files?:[{path}]}` | Message (`pending` = members not reached yet) |
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
| POST | `/api/team-peer/inbox` | signed event `{type: accept\|refuse\|bye\|profile\|chat\|message\|vote\|react, …}` | `{ok}` · `401` unsigned / stale / replayed · `403` bad signature |
| GET | `/api/team-peer/files/{fid}` | signed | the file, when the sender is a member of a chat where it was shared |

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
| GET | `/api/extensions` | – | `[{id, name, type:"widget"\|"page", icon, version, enabled, error, has_api, pinned, page_v}]` (pinned: page shown in the sidebar; page_v: page.js mtime in ms, the UI imports `page.js?v=<page_v>` so the module is reused until the file changes) |
| PATCH | `/api/extensions/{id}` | `{enabled?, pinned?}` | `{ok}` (`pinned` on a widget -> 400 `not_a_page`) |
| POST | `/api/extensions/reload` | – | rescans `<workspace>/extensions` |
| ANY | `/api/ext/{id}/{path}` | – | forwarded to the extension's `api.py` `handle()`: return value → JSON, `(status, body)` tuple sets the status, `ValueError` → 400, `LookupError` → 404, other → 500 `extension_error`, 30 s timeout (504 `extension_timeout`), 503 `extension_busy` when the 4 extension threads are all still running earlier calls. A `.` / `..` segment in `path` → `400 bad_path` |
| GET | `/ext/{id}/page.js` | – | page module (ES module) |
| GET | `/ext/ui-kit.css` | – | the UI kit of extensions (`server/maxxing/assets/ui-kit.css`): `ui-*` classes scoped to `.mx-ext` (page host) and `[data-mx-kit]` (widget frame), built on the theme variables; the app adds it once when a page extension opens; `ETag` (content hash), `If-None-Match` -> `304` |
| GET | `/ext/{id}/widget-frame` | – | HTML widget document: the bridge (`maxxing.api / resize / theme`, theme from the URL fragment) + the UI kit inlined (`<html data-mx-kit>`) + `widget.html`, `Content-Security-Policy: sandbox allow-scripts allow-pointer-lock` (the UI frames it with the same sandbox; an srcdoc frame would inherit the app's script policy). `/ext/{id}/widget.html` stays the raw file (text/plain) |

The app page (`index.html`) is served with `script-src 'self'` plus the hashes of its inline boot scripts
(`app._app_csp`): a page extension's `page.js` runs in the app, so it may not inject inline `<script>` nor use
`eval` / `new Function` (load code as modules from its own folder).

Extension folder: `<workspace>/extensions/<id>/manifest.json`
`{"id", "name", "type":"widget"|"page", "icon":"<lucide name>", "version", "span"?, "ttl"?: seconds}` +
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
| GET | `/api/stats/tokens?force=1` | – | `{totals, projects:[{name, …}], topics:[{path, …}], sessions:[{id, title, path, archived, updated, …}] (top 100), days:[{date, tokens, cost_usd}] (90 days), latency:{start_s, first_answer_s, turns}, at}` (latency: medians over the last 20 turns of every session: seconds from starting `claude` to its first event / first answer); each group has `input, output, cache_read, cache_write, total, cost_usd, turns, sessions` (sorted by `total`; project `""` = workspace root). Cached 20 s |

## Feed (notifications)
`FeedEvent = {id, at, source, level: "info"|"success"|"warning"|"error", title, body, url, count, read}` (`count` > 1 =
folded repeats). Kept 30 days in `<state>/feed.db`.

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/feed?source=&unread=1&before=<id>&limit=50` | – | `{events: FeedEvent[], more, unread, sources: [{source, total, unread}]}` newest first (`limit` <= 200) |
| POST | `/api/feed` | `{title, body?, level?, source?, url?, dedupe?, group?}` | `{event, duplicate}` (`dedupe` = idempotent per source; `group` folds into the latest unread row of that group, 24 h) · `400 empty\|bad_level\|bad_source` |
| POST | `/api/feed/read` | `{ids?: number[], source?, all?: bool}` | `{unread}` |
| DELETE | `/api/feed/{id}` | – | `{ok}` |
| GET / PUT | `/api/feed/settings` | PUT `{telegram?: bool, rules?: {<source>: "auto"\|"off"\|"silent"\|"loud"}}` (merged) | `{telegram, sources: [{source, label, builtin, rule, own_thread}], hooks: FeedHook[], kinds, rules}` |
| POST | `/api/feed/hooks` | `{name, kind: "stripe"\|"shopify"\|"github"\|"generic", secret?}` | `FeedHook = {id, name, kind, created, url, has_secret}` · `409 exists\|reserved`, `400 bad_kind` |
| PATCH | `/api/feed/hooks/{id}` | `{secret?, regenerate?: bool}` | `FeedHook` (regenerate = new token, the old URL dies) |
| DELETE | `/api/feed/hooks/{id}` | – | `{ok}` |
| POST | `/api/feed/hooks/{id}/test` | – | `{event}` |
| POST | `/api/hooks/{token}` | the service's payload (<= 1 MB) | **public** (no cookie, no CSRF header: the token is the permission). Signatures: Stripe `Stripe-Signature` (5 min tolerance), Shopify `X-Shopify-Hmac-Sha256`, GitHub `X-Hub-Signature-256`, generic `X-Signature: sha256=<hex>` - checked when the hook has a secret; a stripe/shopify/github hook WITHOUT a secret refuses every delivery with `401 secret_required` (+ one folded `security` warning in the feed); a generic hook without a secret accepts the token alone. `200 {ok, duplicate, id}` / `{ok, ignored}` (Shopify / GitHub: a delivery whose signed body was already posted is a duplicate whatever its delivery-id header; Shopify keys a known topic too) · `401 bad_signature\|secret_required`, `404` (unknown token: checked before the body is read), `413` (Content-Length or streamed body over 1 MB), `429` (120/min/hook), `400 bad_json` (also for JSON nested too deep), `400 bad_payload` (valid JSON whose fields have an unexpected shape for that service) |

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
`journal_size_limit` is 4 MB, so `search.db-wal` does not keep its high-water mark.

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/search?q=&kinds=session,file,memory,task&limit=30` | – | `{results:[{kind, id (session id / file path / task id), path, title, snippet, at, score}], took_ms}` — every word required, as a prefix, accent-insensitive, BM25 (title x4), one result per session/file/task; `snippet` marks matches with `\u0002`…`\u0003` |
| GET | `/api/search/stats` | – | `{counts:{session, file, memory, task}, bytes, refreshed_at}` |
