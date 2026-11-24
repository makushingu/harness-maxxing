# API contract (v2.0)

Single source of truth between `server/` and `web/`. Change it here first, then on both sides.

## Conventions
- Base path `/api`. JSON in and out (`Content-Type: application/json`) unless stated.
- Auth: signed cookie `mx_session` (HttpOnly, SameSite=Strict, `Secure` when the request came over HTTPS
  i.e. `X-Forwarded-Proto: https`). Unauthenticated → `401 {"error":"auth_required"}`.
- CSRF: every non-GET request must carry header `X-Maxxing: 1`, else `403 {"error":"csrf"}`.
- Multipart requests (uploads, import, voice): the cookie and the CSRF header are checked **before** the body is
  read (`401` / `403`). Then `413 too_large` if `Content-Length` (or the streamed body) exceeds config
  `upload_max_mb` x 10 files (default 2048; 0 = no cap; + 1 MB of multipart framing; each file is held to `upload_max_mb` itself), and `507 disk_full` if the body does not fit
  in the spool dir (`<state>/tmp/uploads`, where the server spools uploads) with min(`upload_min_free_mb`, 128 MB)
  to spare. The full `upload_min_free_mb` reserve (default 1024) is checked on the destination disk per file.
  Both keys are read from config.json on every request (no restart).
- Other request bodies (JSON, forms...) are capped before they are read (`maxxing/bodylimit.py`), on the declared
  `Content-Length` and, for a chunked body, while it streams: without a valid cookie a mutating request to a route
  that needs one gets `401 auth_required` before a byte is read; the public `/api/auth/*` routes check the CSRF header
  first (`403 csrf`) and take at most 64 kB, `/api/hooks/{token}` 1 MB (a hook of Settings -> Webhooks: its `max_mb`, 1-50). Signed in: 1 MB by default; 16 MB for
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
| GET | `/api/claude/status` | – | `{installed, version, auth:{ok, method:"oauth_token"\|"credentials"\|"api_key"\|null, detail, checked_at:float\|null, error:string\|null, ends_at:float\|null}, default_model, permission_mode, auto_compact_tokens, idle_compact_tokens, idle_compact_after_s, smart_resume_tokens, protect_secrets:bool, short_titles:bool, short_titles_model:bool, auto_update:{enabled:bool, checked_at:float\|null, latest:string\|null, last:{from, to, at:float, ok:bool, error:string\|null}\|null}, models:[{id,label,context_window:int\|null}]}` (`context_window`: as last reported by Claude Code on this server, null if never seen) |
| POST | `/api/claude/auth` | `{kind:"oauth_token"\|"api_key", value}` | stores the secret then runs a test call → `{ok, error?}` (when the test fails, the credential stored before is put back); 400 `invalid` if `value` is shorter than 10 characters or not printable ASCII without spaces |
| DELETE | `/api/claude/auth` | – | removes stored token/key |
| POST | `/api/claude/test` | – | `{ok, model, ms, error?}` (real one-line call) |
| PUT | `/api/claude/settings` | `{default_model?, permission_mode?, auto_compact_tokens?, idle_compact_tokens?, idle_compact_after_s?, smart_resume_tokens?, protect_secrets?, short_titles?, short_titles_model?, claude_auto_update?}` | `{ok}` · default_model: empty, or a model id (1-100 of `A-Za-z0-9._:[]/@-`), else 400 `invalid` · protect_secrets: deny rules on secrets.json and ~/.ssh for every turn · short_titles (default true): a session created with a message and no title gets a short title in the background, made locally, or by the smallest model with short_titles_model (default false) (INTERNALS.md `maxxing.sessions.titles`) · claude_auto_update (default false): the server runs `claude update` while idle, only for a release out for 2 days (INTERNALS.md#maxxingclaude_update) · permission_mode ∈ `bypass` (default) \| `acceptEdits` \| `default` · auto_compact_tokens: 0 = off, else a turn ending above it (at least 100 000) queues a summary turn + fresh thread (default 300 000) · idle_compact_tokens (0..2 000 000, default 200 000; 0 = off, else at least 20 000) / idle_compact_after_s (300..604 800, default 3600): a user message to a session idle for longer, with at least that context, is preceded by a summary turn and runs in the fresh thread · smart_resume_tokens (0..2 000 000, default 60 000; 0 = off, else at least 20 000): a user message after a pause of 5 min+ to a session with at least that context (cache expired, or 100 000+) is sorted by a small model call: NEW -> summary turn first, CONTINUE -> no summary, failure -> the idle rule |

`auth` reflects REAL calls, not the presence of a credentials file: the last session turn or test call with the
current method (success → `ok`, `checked_at`; a sign-in error such as "OAuth session expired…" or "Invalid API
key" → `ok:false`, `error`). A new `claude /login` (credentials file rewritten) or a new token clears an old
failure. With no recent result the server verifies in the background (`claude -p`, cheapest model, 60 s timeout)
at startup and at most every 6 h; a background timeout/network error does not mark the sign-in as failed.
`checked_at:null` = configured but not verified yet. `ends_at` = when a stored `claude` sign-in ends (epoch; null for a token or a key, or when Claude Code did not say).

`models` = the newest model of each family read from Anthropic once a day (`claude_models`; before the first read claude-opus-5-5, claude-sonnet-5-5, claude-haiku-5-5, claude-fable-5-2) + ids observed in logs.

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
Topic   = {name, project, path, description, permission_mode:""|"bypass"|"acceptEdits"|"default", session_count, archived_count:int, running:int, unread:int, errors:int (the unread ones whose last turn failed: red counter), telegram_thread:int|null, agents:[Agent]}
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
  effort: string,                     // `claude --effort` of the next turns: low|medium|high|xhigh|max, "" = Claude Code's default
  real_model: string|null,            // model that actually answered last turn (from the log)
  context_tokens: int|null,           // last turn input+cache tokens
  context_window: int|null,           // context window of the model of the last turn (Claude Code `modelUsage[..].contextWindow`, e.g. 1000000); null = unknown
  archived: bool, favorite: bool, notify: bool,
  source: "web"|"telegram"|"cron",
  cron: bool,                         // started by a scheduled job (not mirrored on Telegram)
  unread: bool,                       // finished after the last /seen, or marked unread by hand (`{seen:false}`)
  last_text: string,                  // first 200 chars of the last assistant text
  error: string|null,
  plan_mode: bool,                    // turns run read-only (`--permission-mode plan`) and end with a plan
  permission_mode: string,            // set by its cron ("" = the topic's, else the global mode)
  plan_ready: bool,                   // a plan-mode turn finished OK: its plan waits for POST /plan/approve
  approvals: int,                     // tool calls waiting for the user's Allow / Deny (agent with `approvals`)
  device_asks: int,                   // ask_human requests on the person's devices waiting for them (Devices)
  compact_tokens: int | null,         // its own compaction threshold (Jarvis's conversation: Jarvis settings), null = the server's
  code_repos: [str]                   // git repositories its turns changed (Changes view, terminal tabs), at most 8
}
```
| GET | `/api/sessions?path=&archived=0\|1` | – | `[Session]` sorted by `updated` desc (no path = all) |
| POST | `/api/sessions` | `{path, message?, title?, model?, effort?, attachments?:[filepath], plan_mode?:bool, voice?:filepath, client_id?}` (`client_id`: as for `/messages`, for the first message) | `Session` (starts the first turn if message or voice) |
| GET | `/api/sessions/{id}` | – | `Session` |
| PATCH | `/api/sessions/{id}` | `{title?, model?, effort?, archived?, notify?, plan_mode?, favorite?, path?}` | `Session` (`plan_mode:false` also clears `plan_ready`; `favorite` is carried over by a hand-off; `path` moves the session to another topic and its Claude transcript with it - `400 bad_path`, `409 busy` while a turn runs or messages wait; `model`: an id of letters, digits and `._:@/[]-`, 100 characters at most, not starting with `-`, else `400 bad_model`, also on create; `effort`: `low|medium|high|xhigh|max` or `""` (Claude Code's default) -> `claude --effort`, else `400 bad_effort`, kept by a hand-off) |
| POST | `/api/sessions/{id}/plan/approve` | `{text?}` (shown in the thread as the user's message) | `{queued:bool, session:Session}` — plan mode off, then a turn that tells Claude to implement its latest plan (queue item flag `plan_approved`, kept by steer) |
| DELETE | `/api/sessions/{id}` | – | `{ok}` (stops a running turn, moves the session to the trash) |
| POST | `/api/sessions/{id}/messages` | `{text, attachments?:[filepath], voice?:filepath, client_id?, mentions?:[{kind: jarvis|session|agent|team, ref}]}` (`mentions`: the @ of the composer, refs from `/mentions` below; the server resolves them (unknown ones and the session itself dropped, at most 8) and adds to the prompt, not to the displayed message, the command that writes to each (`maxxing sessions send` / `agents send` / `team send`); its `user` event keeps `mentions: [{kind, ref, label, group?, avatar?}]` (never the command), drawn as chips; `client_id`: the sender's own id for the message, `[A-Za-z0-9_-]{1,64}`, kept in `client_ids` of its queue item (`queue_items`) and of its `user` event, so a page reloaded mid-send can tell whether it arrived; `voice`: a voice message sent directly - uploaded first with `/api/uploads`, queued at once, transcribed by the server, then its transcript is the prompt) | `{queued:bool, session:Session}` · `409 voice_off` (transcription not ready) |
| GET | `/api/sessions/{id}/mentions` | - | `{items:[{kind: jarvis|session|agent|team, ref, label, hint, state?, avatar?, group?}]}`: who the composer's @ can name - Jarvis (its feature on, not from its own conversations: one row `ref: jarvis`, its conversation of the moment), the other sessions (running first, then the most recent 60, not archived, no agent chats, none of Jarvis's conversations), the agents (Agents page on), the Team contacts and groups (Team page on) |
| DELETE | `/api/sessions/{id}/queue` | – | clears queued messages |
| POST | `/api/sessions/{id}/ask` | `{question}` | `{answer, cost_usd, duration_ms}` — side question: Claude answers from a throwaway copy of the session's thread (read-only, nothing saved: the running turn, queue and log are untouched). 409 `no_thread` (never answered yet) / `busy` (one already running for this session), 429 (2 running), 504 (240 s) |
| POST | `/api/sessions/{id}/queue/take` | – | `{messages:[{text, attachments}], session}` — removes the queued user messages and returns them (the composer's **Edit**: they come back in the composer and are sent again as a normal message) |
| POST | `/api/sessions/{id}/hide` | `{at, hidden=true}` | `{ok}` — hides (or shows again) the user message whose `at` is given: appends `{type:"mx_hide", ref, hidden}` to the raw log (nothing is erased; Claude's own thread is untouched), streamed as a `hide` event; 404 when no user message has that `at`, nothing written when it is already in that state. The UI offers it for a message whose turn ended without any answer (stopped) and drops that turn's rows |
| POST | `/api/sessions/{id}/inject` | – | `{injected:bool, reason, session}` — **Add to plan**, without interrupting: the queued user messages become ONE message written into the running turn (SIGUSR2: the runner writes it to Claude's stream-json stdin), read by Claude at its next step, between two tool calls. When the runner cannot write it (the turn just ended), the message stays queued and runs after the turn - never lost, never sent twice. `injected: false` with `reason`: `idle` (no turn running / nothing queued), `unsupported` (a runner from before this route), `summary` (a compact / hand-off summary runs), `voice` / `plan` (voice messages and plan approvals run as their own turn: steer or wait) |
| POST | `/api/sessions/{id}/steer` | – | `{steered:bool, interrupted:bool, session}` — while a turn runs: the queued user messages become ONE message (`steer: true`) at the head of the queue and the runner gets SIGUSR1: it ends the current turn (only that one: meta `steer_turn` = `turn_id`) and runs that message next in the same Claude thread, prefaced so Claude continues the task with it. A compact / handoff turn is not interrupted (`interrupted:false`, the message runs right after it). `steered:false` when idle or nothing is queued |
| POST | `/api/sessions/{id}/stop` | – | `{ok}` (clears the queue, aborts the running turn; returns once settled, ≤ ~10 s). During an idle-compaction summary only the summary is aborted: the message waiting behind it (queue item `held`) stays and runs |
| POST | `/api/sessions/{id}/compact` | – | `{ok}` summary → fresh Claude context, same session · `409 busy` while running · `400 empty_session` |
| POST | `/api/sessions/{id}/handoff` | – | `Session` (new session seeded with a summary; old one archived). Messages sent to the new session before the summary arrives are queued (`queued:true`) and run after the seed (10 min at most, or at once when the summary fails) |
| POST | `/api/sessions/{id}/seen` | `{seen=true}` (optional) | `{ok}` - read; `{seen:false}`: unread again until read ("Mark as unread") |
| GET | `/api/sessions/{id}/events?tail=N` | – | last events, read backwards from the end (whole log lines, at least N events when available, max 5000): `{events, start, next, more_before:bool, state}` — `start` = offset of the first line returned, `next` = end offset (start the stream there). What the UI uses to open a thread |
| GET | `/api/sessions/{id}/events?before=<offset>&limit=N` | – | events strictly before `offset` (backward paging, "Show earlier messages"): `{events, start, next:offset, more_before, state}` · `{events:[], reset:true, state}` when `offset` is not a line boundary of the current log |
| GET | `/api/sessions/{id}/events?from=0` | – | forward reading `{events:[Event], next:int, state, more:bool}` (≤ 4 MB of log per call; `more` = call again from `next`) · `reset:true` when `from` is beyond the end / not a line boundary |
| GET | `/api/sessions/{id}/stream?from=0` | – | **SSE**. `event: events` `data: {events, next}` · `event: state` `data: Session` · `event: reset` `data: {}` then end of stream when the log was rewritten or shrank (or `from` is stale): reload with `?tail=` · heartbeat comment every 15 s. New lines and state changes are pushed ~0.05-0.15 s after they are written (inotify on the sessions folder; without it the stream polls every 0.1 s while the session runs) |
| GET | `/api/sessions/search?q=` | – | `[{id, title, path, snippet, at}]` (served by the full-text index, see Search; max 50) |
| GET / POST | `/api/sessions/open` | POST `{open?:[id], close?:[id], order?:[id], tabs?:bool, front?:id}` | `{ids:[id]\|null, rev, tabs?, front?}` — the sessions open on screen, shared by every browser of the user (a column on a computer, a tab on a phone), with the Tabs / Zones mode and the session in front last chosen on one of them: ids in the order they were opened, `null` while no browser has shared its own; `rev` grows with each change (a browser ignores an answer older than the one it applied). POST opens, closes, then sorts by `order` (ids it does not name stay after); bus topic `open_sessions`. A deleted session leaves the list |
| POST | `/api/uploads?path=<topic path>` | multipart `file` (multi) | `{files:[{path, name, size, mime}]}` saved in `<topic>/attachments/YYYY-MM/` · each file `413 too_large` over `upload_max_mb`, `507 disk_full` when it would leave less than `upload_min_free_mb` free on the destination disk (all or nothing: the files saved before it in the same request are removed); the whole request is capped at 10 files' worth (see Conventions) |

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
  // from?: {kind: session|agent|cron|feed|mail|group|manual|cli|github|system, title?, path?, session?,
  //         reports?:[{id, outcome: done|asks|failed}]} - not typed by the owner (shown as a card); shown?: the part
  //         of the text meant for the owner (the rest is instructions for Claude)
{type:"voice_text", text, error:str|null, stopped?:true, at}   // transcript of the voice message just above (error: not transcribed, nothing sent to Claude)
{type:"assistant", text, at}                       // markdown
{type:"thinking", text, at}
{type:"tool_use", id, name, input, input_lines?, summary, at}     // summary = one-line human string ("Read src/app.py", "Bash: ls -la")
                                                    // input text fields over 20,000 chars are clipped; input_lines = {field: real line count} of the clipped top-level ones
{type:"tool_result", tool_use_id, text, is_error, at}   // text truncated to 20 kB
{type:"init", model, cwd, at, same?}        // same: a turn of a Claude process that already ran one (its background tasks run on)
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
| GET | `/api/files/thumb?path=&w=320&h=0&v=&anim=0` | – | webp thumbnail for images, videos and PDFs (ffmpeg, video: frame at 1 s; PDF: first page through `pdftoppm`), cached server side; without ffmpeg images fall back to the original · other types `415`. `w` ≤ 4096; `h` (images, videos): at least this height too, for a box of fixed height (wide pictures). `anim=1` (chat): a `.gif` of at most 8 MB (`GIF_ANIM_MAX`) is served as it is (`image/gif`, it moves), a bigger one gets the still. Cache: `no-cache` (revalidated), or for good with `v`. Same CSP rule as `/raw` (an SVG fallback is sandboxed) |
| GET | `/api/files/preview?path=&w=2048&v=` | – | the image for the viewer: a WebP at most `w` px wide (64-4096, default 2048) when the original is heavy (over 300 kB, or a format the browser cannot show: then converted), else the original (`.gif` and `.svg` always as they are; no ffmpeg: the original). `v`: as on `/raw` · `404 not_found` · `415 unsupported` (not an image, or a format this server cannot convert) |
| GET | `/api/files/archive?path=` | – | lists a zip, tar (gz/bz2/xz) or single `.gz` without extracting it: `{path, format:"zip"\|"tar"\|"gzip", entries:[{name, size, dir, mtime}], count, total_size, truncated, size}` (at most 5,000 entries, 256 MB read and 3 s: then `truncated`; cached per file version) · `404 not_found` · `415 unsupported` (another format, or unreadable) |
| GET | `/api/files/pdf?path=` | – | `{pages, ratio, mtime}` for the page-by-page PDF reader (browsers that show no PDF in the page: most phones): number of pages, height / width of the first one (`pdfinfo`) · `404 not_found` · `415 unsupported` (unreadable or protected PDF, or `pdfinfo` / `pdftoppm` / `ffmpeg` missing: the UI keeps the browser's own viewer) |
| GET | `/api/files/pdf/page?path=&n=1&w=1280&v=` | – | page `n` as a WebP, `w` rounded up to 640, 1280 or 2048 px wide (`pdftoppm` + ffmpeg, kept with the thumbnails, one render per page at a time). Cache as `/thumb` · `404 not_found` (not a PDF) · `415 unsupported` (no such page, or not rendered) · `422` (`n` < 1) |
| GET | `/api/files/pdf/text?path=` | – | `{text, truncated}`: the words of a PDF in reading order (`pdftotext`), for the viewer's "Copy the text"; `text` is empty for a scan, `truncated` past 2 MB of text · `404 not_found` (not a PDF) · `415 unsupported` (unreadable or protected PDF, or `pdftotext` missing) |
| GET | `/api/files/doc?path=` | – | an office document read without any converter installed (`documents.py`, zip + XML only): `{path, mtime, size, type, truncated, …}`; `type: "text"` (`.docx` `.docm` `.odt`) and `"slides"` (`.pptx` `.pptm` `.ppsx` `.odp`) carry `markdown` (headings, bold / italic, lists, tables, links, pictures as `![](<name>)` for `/doc/media`, one `## N. Title` per slide with its notes as a quote); `type: "sheets"` (`.xlsx` `.xlsm` `.ods`) carries `sheets: [{name, rows: [[text]], truncated}]` (visible sheets, values as displayed: dates, times, percents; at most 5,000 rows × 200 columns a sheet, 300,000 cells, 40 sheets). Limits: 16 MB an XML part, 8 s, 1.5 M characters: then `truncated`. A DTD is refused · `404 not_found` · `413 too_large` · `415 unsupported` (another format, old `.doc` / `.xls` / `.ppt`, damaged, password) |
| GET | `/api/files/doc/media?path=&name=&v=` | – | a picture stored in the document (`name` as given by the Markdown of `/doc`; png, jpeg, gif, webp, bmp, ≤ 24 MB), same headers as `/raw` · `404` anything else |
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

## Themes (Settings -> Appearance, `maxxing/themes.py`)
Installed themes, read-only: `<workspace>/themes/<id>/theme.json` (format: docs/user/39-themes.md), installed by Claude
with `maxxing themes install` (never from the UI). Each theme is returned checked and cleaned: only variables of
`themes.TOKENS`, values re-validated by kind (colors, sizes, shadows, numbers; no `url()`, `var()`, `;`, braces), text
pairs below their contrast dropped. The web app writes them as CSS rules on `html[data-theme-id]` (`lib/themes.ts`).
`Theme = {id, name, description, author, version, homepage, base: solid|glass, modes: [light|dark], light: {token: css},
dark: {...}, options: {mode?, accent?, tint?, font?, mono?, density?}, own_accent, own_surfaces,
wallpaper: {light: url|null, dark: url|null}, preview: url|null, css: str|null, css_state: none|on|stale, warnings: [str]}`.
`css` = the theme's one field of advanced CSS, checked by `themes._css` (refused as a whole on `url()`/images, any
at-rule but `@media|@supports|@container`, `position: fixed`, `<`, `\`, unbalanced braces or quotes; 16 KB); the web
app nests it in `html[data-theme-id="<id>"]{…}` and applies it only when `css_state` is `on`: `<theme>/.css-check.json`
`{"ui": fingerprint, "css": sha256 of the css}` matches `themes.ui_fingerprint()` (hash of the names of the served build's `assets/*.css`, i.e.
of the interface's CSS) and the css itself. Written by `install` and `maxxing themes verify <id>`; an update that changes
the interface's CSS, or an edit of the rules, makes it `stale` (off).

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/themes` | - | `{themes: Theme[], errors: [{id, error}]}` (folders that are not usable, with the reason) |
| GET | `/api/themes/{id}/file/{name}` | - | an image the theme names (`wallpaper`, `wallpaper_dark`, `preview`), else 404 |

## Webhooks & events (Settings -> Automate, `maxxing/webhooks.py`)
Automations without AI: one trigger + one action. Made from the pages' short form (`POST /api/webhooks`, `PATCH`
with the whole `trigger` / `action`, the form merging what it does not show) or by Harness from a session
(`maxxing webhooks add`); the pages Webhooks (trigger `in`) and Events (trigger `event`) also show, switch, test,
replay and copy the URL.
```
Hook = {id:"w_xxxxxxxx", name, description, enabled, created, updated, owner:null,
        trigger: {kind:"in", source:"stripe"|"shopify"|"github"|"generic"|"phone", methods:["GET"?,"POST"?],
                  max_mb:1-50, reply:"now"|"wait", filter:{events?:[glob], branch?:glob}}
               | {kind:"event", on:"feed", source?, levels?:[level], contains?}
               | {kind:"event", on:"agent"|"cron", agent?|cron?, when:"any"|"ok"|"fail"},
        action:  {kind:"shell", command (one line), cwd?, timeout_s:1-3600 (300)}
               | {kind:"call", url (fixed, or {{key:NAME}} from the vault), method, headers:{k: v with {{path}} / {{key:NAME}}}, body:"raw"|"json"|template,
                  sign:bool (X-Harness-Signature: sha256=<hmac of the body>), retries:0-5 (2), timeout_s:1-60 (15)}
               | {kind:"store", fields:{column: "path.from.the.payload"}, keep:rows (100000)}
               | {kind:"notify", level?, title?, body?, url?}   // templates; empty title: the feed's parser of the source
        queue: {parallel:1-4 (1), max_waiting:0-500 (50)}, report:"never"|"fail"|"always",
        // templates {{path}}: the payload's keys, then payload / event / query / hook / call; {{key:NAME}} in headers and url
        // read-only:
        url:string ("" for events), has_secret, has_sign, needs_secret, last_call:Call|null, calls_24h, waiting,
        data?:{rows, today, days:[7 counts], last_id}}      // store hooks
Call = {id, at, trigger:"in"|"event"|"test"|"replay", event, summary, status:"queued"|"running"|"ok"|"failed"|"ignored",
        http?, exit?, duration_s?, output? (last 4 kB), error?, attempts?, of? (replay: the call replayed)}
```
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/webhooks` | – | `{hooks:[Hook], feed_hooks:[{id, name, kind, url, has_secret, created, agent:path\|null}], https:bool}` (feed_hooks: the notification webhooks (feedhooks.py) and those of agents, in the same list of Settings -> Webhooks; managed with `/api/feed/hooks`) |
| POST | `/api/webhooks` | Hook fields + `secret?` | `Hook` · `400 invalid\|bad_secret`, `409 exists` (same name) |
| GET | `/api/webhooks/{id}` | – | `Hook` · `404` |
| PATCH | `/api/webhooks/{id}` | `{enabled?, description?}` or Hook fields (top-level keys replaced) | `Hook` · `409 owned` |
| DELETE | `/api/webhooks/{id}` | – | `{ok}` (its calls and rows too) |
| POST | `/api/webhooks/{id}/rotate` | – | `Hook` with a new `url` (the old one stops at once) |
| POST | `/api/webhooks/{id}/secret` | `{secret}` (`""` removes it) | `Hook` |
| POST | `/api/webhooks/{id}/test` | – | `{id, status:"queued"}`: a realistic sample of its source / event, filters skipped |
| GET | `/api/webhooks/{id}/calls?limit=50` | – | `{calls:[Call]}` newest first (the last 50 kept) |
| GET | `/api/webhooks/{id}/calls/{call}` | – | `Call` + `{request:{method, content_type, headers (secrets as ***), query, event, files, size}, body (64 kB), body_truncated}` |
| POST | `/api/webhooks/{id}/calls/{call}/replay` | – | `{id, status:"queued"}` (a new call with the same request) · `404` (no longer kept) |
| GET | `/api/webhooks/{id}/data?after=&limit=100&format=json\|csv` | – | `{rows:[{id, at, call, data, fields?}], stats}` · csv: a download |
| GET / POST | `/api/hooks/{token}` | anything (JSON, form, multipart files, text; GET: the query) | **public**. A hook of Settings -> Webhooks: `202 {ok, call}`; reply "wait": the action's result within 30 s (shell: `$MAXXING_RESPONSE_FILE` or stdout, type sniffed; call: the remote answer as is; else `{ok, call}`), `502 {error:"failed", exit}`, `504 {error:"timeout", call}` · `200 {ok, ignored}` (filter), `{ok, duplicate}` · `401 secret_required\|bad_signature\|bad_key`, `405` (method), `413` (over `max_mb`), `429` (120/min), `503 disabled\|busy` (+ `Retry-After`). Any other token: a feed webhook (below, POST only) |

The shell action gets the call as data, never in its command line: stdin = the body; `MAXXING_WEBHOOK_BODY` (file),
`_PAYLOAD` (parsed JSON / form / query, file), `_HEADERS` (request.json: method, headers, query, files), `_QUERY`
(JSON), `_FILES` (folder, or empty), `_EVENT`, `_METHOD`, `_TRIGGER`, `_ID`, `_NAME`, `_CALL`, `MAXXING_RESPONSE_FILE`
(what a "wait" caller gets; `<file>.type` = its content type), plus the vault keys exposed to jobs. It runs in a transient
unit `maxxing-hook-<id>-<call>` (jobs slice, timeout), like a cron job.

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
| GET / PUT | `/api/settings` | `{timezone, language:"en"\|"fr", public_url, files_root, presentation_default?, daily_budget_usd:number ($ per day for the whole server, 0 = no budget, at most 100000; `400 invalid_daily_budget`), limit_retry:bool, limit_retry_delay_s:int, usage_widget:bool, git_page:bool, infra_page:bool, mail_page:bool, devices_feature:bool, maxxing_mode:bool, memory_max_lines:int, cpu_priorities:bool, result_line_hidden:["model"\|"duration"\|"cost"\|"tokens"\|"cache"], donation_hidden:bool, sidebar_order:[route], nav_badges_hidden:["/"\|"/sessions"\|"/team"\|"/agents"]}` (`nav_badges_hidden`: Settings -> Features -> Badges, the sidebar pages whose counter badge is off, default `[]`, unknown values = 422, stored in canonical order) (`donation_hidden`: hides the donation links of What's new, Feedback and Settings -> License for every browser, default false; the Support card of Settings -> About stays) (`result_line_hidden`: parts of the line under each answer that are hidden, default `[]`, unknown values = 422, stored in canonical order) (`git_page`: the Git page `/git` and its sidebar entry, default false) (`maxxing_mode`: beta, Maxxing mode of the Sessions page - its switch, meter, driver and Alt+M -, default false) (`memory_max_lines`: 0 = no limit, else 50-5000, default 100) (`limit_retry`: a cron job or an agent run stopped by Claude's usage limit starts again `limit_retry_delay_s` after the reset read from the message or the reported limits, default true and 60; delay 0-3600, `400 invalid_limit_retry_delay`) (`cpu_priorities`: CPU weights of the server / turns / jobs slices, default true; a change rewrites the slices at once, `cmd_core.ensure_cpu_slices`) — a new `timezone` also switches the server zone (`timedatectl`, cron restarted); PUT ignores the fields equal to the stored config (neither checked nor applied: the web app sends the whole object) |
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

## Devices
`maxxing/devices/` + `api/devices.py`, feature `devices_feature` (Settings -> Features, off by default). The person's
computers and phones run Harness Link (`link/`, `android/`; contract `link/PROTOCOL.md`, v2) and connect OUT to this
server; Claude uses them through the per-turn MCP `harness-devices` (`devices_mcp.py`, stdio, given by the runner to a
turn that sees at least one device).
```
Device = {id:"dev_<8 hex>", name, os:"linux"|"darwin"|"windows"|"android", os_name, kind:"desktop"|"android", arch,
  version, created, last_seen, confirmed:bool, mode:"view"|"control", scope:["*"] | ["project:<name>", "agent:<path>"],
  caps:[…], screen:{w,h,scale}|null, note, ip,
  online, paused, human (the person has it), claude (Claude acted in the last 15 s), used_by:{session,owner,at}|null,
  watched, hello:{v,os,arch,caps,screen,note}|null}
DevicesStatus = {feature, available:[<target>…] (what can be downloaded now), latest (link.json version), devices:[Device],
  invites:[{os, expires_at}] (codes not used yet), asks:[DeviceAsk], actions:[{at,device,tool,args,ok,ms,session,owner,error?}]}
DeviceInvite = {code (8 characters, once, 15 min), os, expires_at, expires_in, server, commands:{sh, ps1}, link
  (<server>/link/<code>, the phone's page = the QR code), deeplink (harnesslink://pair?s=<server>&c=<code>),
  downloads:{<target>: url}}
DeviceAsk = {id, session, owner:"session:<path>"|"agent:<path>", device, device_name, message, at, expires, status, note}
target = linux-amd64|linux-arm64|darwin-amd64|darwin-arm64|windows-amd64|windows-arm64|android
```
Who sees a device: its `scope` (a session of project `acme`: `*` or `project:acme`), and an agent turn only the ids of
its agent.json `devices` (a free agent also the devices whose scope names it: `agent:<path>`). `mode: view`: Claude
gets `devices`, `screenshot`, `zoom`, `ui_tree`, `ask_human`, `wait`, `screen` only (`screen {device, screen: n|-1}`
sets the device's `display` like `PUT`, waits up to 3 s for the app's new hello, answers with a shot). Downloads: `MAXXING_LINK_BIN_DIR` (a local
build), else the release of `maxxing/link.json` (`{version, url, files:{<name>: sha256}}`, cached in
`<state>/devices/bin/`, checked). A desktop binary is sent with the trailer `<json {server, code}><uint32 BE
len>HMLINK01`; the APK as it is. The public code routes count wrong codes per client: 20 in 10 min -> `429 throttled`.
They answer `404 off` while the feature is off.

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/devices` | – | `DevicesStatus` |
| POST | `/api/devices/invites` | `{os?}` | `DeviceInvite` · `409 off` (feature off), `429 too_many` (10 codes waiting) |
| POST | `/api/devices/{id}/confirm` | `{ok}` | `{ok}` - yes: the device may be used; no: it is dropped and its app gets `unpair` · `ok:false` when it does not wait |
| PUT | `/api/devices/{id}` | `{name?, mode?: view\|control, scope?, display?: -1..15 (screen used, -1 = main)}` | `Device` (+ `screens`: the last `hello.screens`, kept offline) · `400 bad_scope`, `404`, `422` |
| DELETE | `/api/devices/{id}` | – | `{ok}` - its token is revoked at once, its app gets `unpair` (forgets this server, stops), its requests are skipped |
| GET | `/api/devices/session/{sid}` | – | `{using:[{id,name,os,online,human,at}], asks:[DeviceAsk]}` - the session's line ("Claude is using …") |
| GET | `/api/devices/asks?session=` | – | `{asks:[DeviceAsk]}` (pending) |
| POST | `/api/devices/asks/{id}` | `{action: done\|skip, note?}` | `DeviceAsk` (decided; the person's control is released) · `404`, `409 decided` |
| POST | `/api/devices/live-token` | – | `{token}` (30 s, one use) for `WS /api/devices/{id}/live?t=` |
| WS | `/api/devices/{id}/live?t=` | the signed-in cookie + a live token | binary JPEG pictures (~3/s, only while someone watches) + `{"t":"state", device: Device, me, asks}`; in: `{"t":"input", a, x, y, x2?, y2?, sw, sh, button?, double?, dx?, dy?, text?, keys?, ms?}` (pixels of the picture shown, `sw`/`sh` its size: the person takes over), `{"t":"take"}`, `{"t":"release", done?: true\|"skip", note?}` (answers the device's pending requests) · close `4403`, `4404` |
| GET | `/api/devices/install/<code>.sh\|ps1` | – | install script: stops an older copy and removes its login entry, downloads the app with its trailer, puts it on the PATH, then runs it in the foreground of that terminal (sh: `~/.local/bin/harness-link`, quarantine removed on macOS, `exec … </dev/tty`; ps1: `%LOCALAPPDATA%\HarnessLink\harness-link.exe`, user `Path`) · public, `400 bad_code`, `410 expired`, `429` |
| GET | `/api/devices/download/{target}?code=` | – | the app (desktop: + pairing trailer; `Content-Length` set; android: the APK) · public, `400`, `404 not_available`, `410`, `429` |
| POST | `/api/devices/pair` | `{code, name, os, arch, version, caps}` | `{device_id, token}` - the code is used up, the device waits for `/confirm` · public, `400 bad_code`, `410 expired`, `409 too_many`, `422`, `429` |
| WS | `/api/devices/ws` | `Authorization: Bearer <device token>` | Harness Link protocol v2 (PROTOCOL.md); a device not accepted yet is held (it gets `{"t":"access","ok":false}`), then `access` `ok:true` once accepted or `unpair` if refused or after 15 min; `access` again when its mode changes; `display` (the screen chosen, `PUT {display}`), `watch` (live view open) · unknown / revoked token: refused before the handshake (HTTP 403) |
| POST | `/api/devices/mcp/{sid}` | JSON-RPC, `Authorization: Bearer <the turn's token>` | loopback only: `tools/list`, `tools/call` of the turn (`<state>/devices/turns/<sid>.json`) · `403` |

`GET /link/<code>` (public, not under /api): the phone's pairing page - Download the app (APK), Open in Harness Link
(the deep link), the server and the code to type by hand; `410` when the code expired or was used, no script.

Server -> device frames (v2) and what the server adds: `shot {id, max_w, quality}` (+ `crop:{x,y,w,h}`, `sw`, `sh` for
`zoom`: a region in the space of the last picture; an app that ignores it sends the whole screen), `input {id, a, x, y,
x2, y2, sw, sh, button, double, dx, dy, text, keys, ms}`, `tree {id, sw, sh}`, `tap_node {id, node}`, `set_text {id,
node, text}`, `apps {id}`, `open {id, app}`, `state {busy, by: "claude"|"human"|null}`, `unpair`.

## Voice (speech-to-text)
Claude cannot listen: audio is transcribed on the server (web mic button + Telegram voice notes).
```
VoiceStatus = {settings:{engine:"off"|"local"|"groq"|"openai", model:"tiny"|"base"|"small"|"medium", language:"auto"|"<iso>", auto_send:bool, direct:bool, mic:bool, call:bool},   // mic / call (default true): the mic button and the voice mode button of the message boxes;   // direct (default true): the web mic sends the recording at once
  ready:bool, reason:"off"|"no_ffmpeg"|"not_installed"|"no_key"|null, ffmpeg:bool,
  local:{installed, loaded:str|null, recommended, ram_gb, cpus, models:[{id, size_mb, present}]},
  keys:{groq:bool, openai:bool}, key_names:{groq:"GROQ_API_KEY", openai:"OPENAI_API_KEY"},
  install:{state:"idle"|"running"|"done"|"error", step:"deps"|"model"|null, progress:0..1|null, model, message, error, at},
  max_seconds:900}
```
| GET | `/api/voice` | – | `VoiceStatus` (the UI polls it every second while `install.state = running`) |
| PUT | `/api/voice/settings` | partial settings | `{ok, settings}` · `400 invalid_language` · `422` bad enum. Default model when never chosen: `small` (`base` with < 4 GB RAM) |
| POST | `/api/voice/install` | `{model?}` | starts the background job: `uv sync --extra voice` when faster-whisper is missing, then the model download → `install` object · `409 busy` |
| DELETE | `/api/voice/models/{model}` | – | `{ok}` (deletes a downloaded local model) · `409 busy` while that model is being installed |
| POST | `/api/voice/transcribe` | multipart `audio` (+ form `path`? topic path, `language`?) | `{text, language, duration_s, engine, model, ms, audio_path}` — `path` keeps the original file in `<topic>/attachments/voice/YYYY-MM/` (`audio_path`, else null). Any format ffmpeg reads (webm/opus, ogg/opus, m4a, mp3, wav, mp4), ≤ 100 MB, ≤ 15 min · `400 bad_path` (`path` not a topic, `/` included) · `409 voice_off` · `503 not_installed\|no_key\|no_ffmpeg` · `413 too_long\|too_large` · `422 bad_audio\|empty_audio` · `502 engine_error\|bad_key\|download_failed` |

Telegram: voice notes and video notes in a session thread (not audio files: attachments) are downloaded, transcribed, echoed as
`🎤 <transcript>` and sent to the session as the user message (attachment = the audio file). Engine off → a hint.

## Voice mode
A call in a session: a voice talks with the user and hands real work to the session. The voice converses itself (small
talk, news of the work, what the last answer said) and decides when the session works; then the session gets **the
user's own words**, never a rewrite, through the usual send route with `call: <language>` (`POST
/api/sessions/{id}/messages`: the turn's prompt gets `runner.CALL_PREFACE`, "answer short and easy to say, in that
language", not shown in the log); while the session works the browser then calls `POST /api/sessions/{id}/inject` so
the message joins the running turn. Without any model the server sets aside noise and what Whisper makes up on silence,
the voice's own echo, "stop" (stops the work at once) and language requests (`voicecall.classify` / `sort`), and keeps
one language per call (set by the first sentence, heard in any language; then changed on request or when a whole
sentence of 3 words or more is clearly in another one). The end of each turn of the session is given to the voice to
tell, and news of a long one now and then. Cloud voices get the same rules as tools (`ask_session` takes no argument:
the browser sends the provider's transcription of the user; `session_status`, `stop_session`, `read_last_answer`);
their transcriptions are sorted by `/call/sort`.
```
CallStatus = {settings:{mode:"local"|"cloud", provider:"openai"|"gemini"|null, openai_key, gemini_key (vault names|null),
    openai_model, openai_voice, gemini_model, gemini_voice, talker_model:"haiku"|"sonnet" (default sonnet), local_voice:"auto"|<voice id>,
    local_speed:0.8-1.5 (default 1.15), silence_ms:800-5000 (default 1800)},   // local_voice is used for sentences in its own language only
  provider,            // used in cloud mode: chosen, else the only one with a key
  keys:{openai|gemini:{found:[vault names that look like its key], using:name|null}},
  local:{ready, reason:"stt"|"tts"|null, tts:{ready, voices:[ids installed], catalogue:[{id, name, lang}], install:{state, error}}},
  cloud:{ready, reason:"choose"|"choose_key"|"no_key"|null}, ready, voices:{openai, gemini, local}, speed_range:[0.8, 1.5], silence_range:[800, 5000]}
```
| GET | `/api/voice/call` | – | `CallStatus` |
| PUT | `/api/voice/call/settings` | partial settings (`provider: ""` = none) | `CallStatus` · `400 invalid_*` |
| POST | `/api/voice/call/start` | `{session, language?, resume?}` (`resume`: cloud reconnection of the same call, Gemini's resumption handle or empty) (the interface language: listened for first, then English) | local: `{mode:"local", call, language, silence_ms}` (starts the voice: `claude -p --input-format stream-json`, no tools, kept for the call, max 3, hung up after 10 min idle; phrases said without it generated ahead); the key never leaves the server · `409 local_not_ready\|cloud_not_ready` · `502 bad_key\|provider_error` |
| POST | `/api/voice/call/{call}/turn` | multipart: `audio` (WAV) or `text` = a sentence of the user, with `context` (the session's state line), `busy`, `saying` (the sentence the voice was saying when the user started: a transcript made mostly of its words is its echo); or `event` (the answer of an ended turn) + `outcome:"answer"\|"failed"\|"done"`; or `outcome:"progress"` + `note` (the running turn's last text) / `tool` (its last tool) | NDJSON stream: `{heard, kind:"ask"\|"stop"\|"lang"\|"empty", language}` first for a sentence (`empty`: nothing follows), `{action:{type:"ask", request}}` (`request` = the user's own words since the last hand-over, with the voice's question when they answered one) or `{action:{type:"stop"}}`, `{say, url, seconds}` per sentence (WAV, `/api/voice/said/<name>`, in the call's language), `{error, code}` (the voice failed: a sentence of the user is handed over anyway), `{language}` (changed), `{done, empty?}` |
| POST | `/api/voice/call/sort` | `{text, language, expecting?}` | `{kind, language}` — the same sorting, for a sentence transcribed by a cloud voice |
| POST | `/api/voice/call/{call}/end` | – | `{ok}` |
| GET | `/api/voice/tts` | – | Piper status `{ready, engine, voices, catalogue, install}` |
| POST | `/api/voice/tts/install` | `{voices?}` | starts the install in `<state>/voice/tts` (own venv, GPL program run apart: `tts_worker.py` keeps the voices loaded) -> the status, `install.state` "running" |
| GET | `/api/voice/said/{name}` | – | a generated sentence (`audio/wav`, kept 10 min) |

## System
| GET | `/api/system/health` | – | `{ok, issues:[{level, code, text}], cpu_pct, cpu_pressure:{avg10,avg60,avg300}|null, cpu_waiting, load, mem:{total,avail}, disk:{total,free,pct}, uptime_s, claude_auth, claude_auth_error, claude_checked_at, backup_age_h, failed_logins_1h, at}` (each issue also has `id` and `seen`; issue `claude_auth`: "Claude is not connected" or "Claude sign-in expired…"; issue `cpu_pressure`: CPU pressure `avg60 >= 40` for 10 min, naming the top unit) (cached 30 s, `?force=1`) |
| GET | `/api/system/cpu` | – | `{enabled, pressure:{avg10, avg60, avg300}\|null, waiting, top:[{unit, kind, name, label, level, pct}], at}` - CPU priorities (`cpu_priorities`) and the units using the processor most (`maxxing/cpu.py`): `pressure` = `some` line of `/proc/pressure/cpu` (null without PSI), `waiting` = `avg10 >= 20`, `top` = 6 units from their cgroup `cpu.stat` (`pct` of the whole machine; Docker containers in one row), `kind` harness / session / agent / heavy / job / browser / docker / other, `level` live / normal / background / other (cached 3 s, `?force=1`; the first call samples 0.5 s) |
| POST | `/api/system/health/seen` | `{id, seen=true}` | the health above, fresh - marks a current issue as seen (or not): it stops counting in the sidebar dot until its text changes (numbers left out of the `id`) or for 24 h; marks in `<state>/health-seen.json` · `404 not_found` |
| GET | `/api/system/services` | – | `[{name, label, active:bool, enabled:bool, since:float\|null, state}]` (claude-maxxing, caddy, tailscaled, cron + config `services_extra`; units not installed are omitted; one `systemctl show` call, cached 10 s, dropped by a service action) |
| POST | `/api/system/services/{name}/{start\|stop\|restart}` | – | `{ok}` (self restart deferred 2 s) |
| GET | `/api/system/logs?unit=&lines=200` | – | `{lines:[str]}` |
| GET | `/api/system/cleanup?force=` | – | `{parts:[{id:"leftovers"\|"caches"\|"journal"\|"apt"\|"previews"\|"trash", bytes, default, items:[{path, why, bytes}]}], disk}`: what Settings -> System -> Disk space can free, measured only (cached 60 s; `maxxing/cleanup.py`) |
| POST | `/api/system/cleanup` | `{parts:[id]}` | `{freed, parts:[{id, freed, error?}], disk}`; 400 `nothing_chosen` / `unknown_part`. Never touches the workspace: projects and attachments are for the "Clean up with Claude" session |
| GET | `/api/system/version?refresh=1` | – | `{version, commit, latest_commit\|null, behind:int\|null, checking:bool, checked_at:float\|null, custom:{count, titles, dirty, rebase}, pending:{at, reason:"conflict"\|"health"\|"dependencies", target_version?, conflicts?}\|null, license:{enabled, key_hint, email, kind, updates_until, expires_at, channel, latest, message, max_servers, moved_to_git, move_error}, report:{at, version, ok, problems}\|null, after:{to, at, notes_session?, notes_path?, done}\|null}` (remote checked every 10 min with git and the update token; nothing on an install still on archives until it has moved to git; `refresh=1` checks now and waits; `commit` and `custom` count/titles/dirty are cached 30 s and while the clone's HEAD / branch ref / index are unchanged, `refresh=1` re-reads them, `rebase` and `pending` are always fresh) |
| POST | `/api/system/update` | – | `{ok}` starts `maxxing update --smart` in a transient unit (after the restart the server verifies, then opens the upgrade-notes session) |
| GET | `/api/system/update/preflight?refresh=` | – | `Preflight` = `{ok, verdict: up_to_date\|simple\|adapt, current, latest, behind, customs:[{id, title, why, files, status: ok\|review\|included\|conflict\|unknown, conflicts, overlap}], unsaved, unsaved_overlap?, web_changes (dirty files under web/dist), ui_build?: {status: ok|failed, error, seconds} (only when a customization changes the web sources), extensions:[{id, name, api, reason}], notes:[{version}], changelog}` - the update simulated in a throw-away git worktree; cached until HEAD / target / unsaved files change; `refresh` fetches first · `502 preflight_failed` |
| POST | `/api/system/update/assist` | – | `{session}`: a session in the update topic that adapts this server's changes then updates |
| GET | `/api/system/update/report` | – | `{report}` = last verification `{at, version, ok, problems, extensions:[{id, name, type, ok, error, skipped?}], checks:[{id, title, check, ok, output}]}` or null |
| POST | `/api/system/update/verify` | – | `{report}`: verify now |
| POST | `/api/system/update/fix` | – | `{session}`: a session that fixes what the last report found · `409 nothing_to_fix` |
| PUT | `/api/system/auto-update` | `{enabled: bool}` | `{ok, enabled}` (config `auto_update`: Settings -> Updates, update by itself while nobody is on the interface and nothing runs; GET `/api/system/version` gives `auto_update:{enabled, tried:{target, version, at}\|null, last_check:float\|null, last:{at, result, why?}\|null}`, `last` = the last pass: `result` as `auto_update.tick()`, `why` for `busy`: browser \| turn \| queue \| aside \| cron \| recent \| update \| work) |
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
| POST | `/api/agents/{p}/{t}/{a}/run` | `{text?, reply_to?, attachments?:[filepath] (≤ 10), call?: "fr"}` (`call`: said on a voice call of the agent's page, in that language: its queue item `call`, as `MessageIn.call`; `attachments`: uploaded first with `POST /api/uploads?path=<agent path>`, each a regular file under `<agent>/attachments/` with no link below it, else `400 bad_attachment`; files only = the text "See the attached files."; the thread's `run` message keeps `attachments`) | `{started: true, session: Session, continued?: true}` \| `{started: false, reason: "disabled"\|"budget"\|"rate"\|"depth"\|"missing"}` - the text is the user's task (not framed). `reply_to` = a thread message id: its session goes on with the text (`continued`, no new session; a gone session -> a new one). A new session gets the last 3 results of the thread as framed context |
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
        | {id: "t_<hex>", kind: "agent", enabled, agent (path of another agent; itself -> 400, unknown when added -> 404),
           on: "ok"|"error"|"any" (default ok), match (substring of its result, "" = any), prompt}
          an "agent" trigger starts the agent on the result of each automatic run of `agent` (not the owner's
          conversation, not a group's turns), debounced like feed events, one hop deeper; its runs have
          trigger "after:<trigger id>", source "agent <name>"; trigger_stats counts them; /test starts it now on the
          other agent's last result (-> the fire answer, not {event})
AgentMessage = {id, at, kind: "note"|"run"|"skip"|"result", text,
                trigger?: "manual"|"cron:<job>"|"feed:<trigger>"|"after:<trigger>"|"telegram"|"agent:<path>", source?,
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
(deny + reason). The owner's conversation (`agents.manager_turn`) is never sandboxed and has no approvals: its
`--settings` = `agent_guard.chat_settings` (the same `permissions.deny` on secrets + Edit on `locked_paths` but its
CLAUDE.md, the rules hook), the topic's permission mode. The `maxxing` CLI refuses everything but `CLI_ALLOWED` when its process belongs to the systemd unit
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

## Harness Browser

`maxxing/browser/` + `maxxing/api/browser.py` (INTERNALS "maxxing.browser"). Off unless `browser_feature` (Settings).
Settings in config `browser`: global values, **profiles** (each one its own Chromium: sign-ins, exit; `main`
= the person's "General", always there, cannot be deleted; also the profile of the projects `general` and `system`) and **exits** (shown as "connections": where a profile's
traffic leaves; `direct` = this server, always there, not stored). **One profile per project** (`project` =
`projects/<name>`, one at most per project): made with the exit and `on_exit_down` of `main`, named
after the project, the first time a turn of the project gets the browser (`active_for`), when an owner view of an
enabled folder is asked, and for every project that has an agent when `GET /api/browser` runs; it cannot be deleted
while its project exists (`409 project`). Who may use it: a `browser` block `{enabled?}` in the `.maxxing.json` of a
project or a topic (topic -> project -> `true`, `browser.SESSIONS_DEFAULT`) and `{enabled?, profile?}` in an agent's agent.json (its
`enabled` is never inherited: `false` unless set). Which profile: a session = its project's; an agent = its `profile` if that profile exists, else its
project's (`profile: "own"` of before = its project's; a project's / topic's `profile` is ignored). **Navigators**
(`navs.py`): a window of tabs in a profile's Chromium; several may share a profile (its sign-ins), each sees only its
tabs: the person's one `me` (its profile stored in `<state>/browser/navigators.json`), `agent:<path>` (every run of an
agent: lasting), `session:<sid>` (the turns of a session, in its project's profile: temporary, its tabs are closed
once no turn, viewer or person used them for `idle_min`; the profile's journal keeps a line). A turn's tools see only its
navigator's tabs (view.py); the person may open tabs in any navigator (they are marked as theirs). Bus topic `browser` on every start / stop /
tab change / request / exit state change (`sessions` too when a turn starts or stops waiting for an exit).
Errors: `{error, message}`.

```
BrowserSettings { ask: bool (true), wait_min: int (30, 1..1440), downloads: bool (false), idle_min: int (30, 5..1440),
                  tab_sleep_min: int (20, 2..720), max_tabs: int (12, 2..30, awake per profile),
                  max_active_profiles: int (3, 1..8), exit_wait_s: int (180, 0..900),
                  search: "google"|"duckduckgo"|"bing" ("google": the address bar's search) }
BrowserProfile  { id (^[a-z0-9][a-z0-9-]{0,23}$, not "direct"), name (<= 40), exit: "direct"|exit id,
                  on_exit_down: "wait"|"vps", project: ""|"projects/<name>" (set by the server) }
                                                                                     (<= 40 profiles, main first)
BrowserExit     { id, name, type: "proxy"|"tailscale"|"wireguard",
                  proxy: url ("socks5://host:port"|"http://host:port"; no scheme = socks5), user
                  tailscale: node (the device used as exit node, its Tailscale IP), login_server ("https://..." Headscale, "" = Tailscale)
                  wireguard: - }                                                     (<= 10 exits)
                  secret (proxy password | WireGuard config | Tailscale auth key) = vault key BROWSER_EXIT_<ID>
                  (`-` -> `_`, upper case, not exposed to turns), never in config.json
ExitView        = BrowserExit + { state: "up"|"down"|"unknown", since, error, latency_ms, test: ExitTest|null, checking: bool,
                  secret: bool (one is in the vault) }
ExitTest        { ok, at, error?, ip, country, country_code, city, operator, asn, kind: "isp"|"mobile"|"hosting",
                  latency_ms, mbps? }        (ip-api.com through the exit; kind "hosting" also when ip-api says proxy;
                  mbps = 2 MB over TLS from a CDN, absent when that part failed)
ProfileRow      = BrowserProfile + { state: "starting"|"running"|"stopped", tabs, awake, mem, turns, control: bool,
                  asks, has_data: bool (its folder exists), gone: bool (a project's whose project was deleted),
                  agents: int (agents whose browser is on and runs on it) }
SessionLine     { session, title, path, first, last, actions, sites: [host] (<= 12), open: bool (its tabs are still
                  open), turns }      (a temporary navigator, from the profile's journal: entries with nav "session:*")
BrowserTab      { key, url, title, by: {kind: "you"|"session"|"agent", sid?, name?, path?}, asleep: bool,
                  front: bool (shown in the live view of its navigator), used, nav }
Navigator       { id: "me"|"agent:<path>"|"session:<sid>", kind: "person"|"agent"|"session", name ("" | the
                  agent's | the session's title), path?, session?, profile: pid|null (an agent whose project's profile
                  is not made yet), running, tabs, awake, page: {url, title}|null, control: bool,
                  watched: bool (a live view shows it), turns, used }
                  (the person's, the agents' with a browser on, sessions with a tab)
BrowserState    { profile, nav: navigator|null (null: the whole profile), state, started, last_use, stops_at, tabs: [BrowserTab], front: key|null,
                  page: {url, title}|null, control: bool (the person has the tab shown), control_by,
                  busy: bool (a turn acted on the tab shown in the last 15 s), turns: [{session, path, kind, nav}],
                  mem, level: ""|"live"|"background" (CPU level of its unit), bytes, blocked: [host] (5 newest),
                  dialog: {type: "alert"|"confirm"|"prompt"|"beforeunload", message, default}|null (open on a page),
                  chooser: {multiple}|null (a page asked for files) }
Summary         { running: [pid], mem, turns: {sid: pid}, tabs: {pid: awake}, cap, server_used, server_total,
                  level: "ok"|"warn"|"critical" }
Waiting         { session, owner, exit, profile, at, resume: bool }      (a turn stopped by a down exit)
OwnerView       { owner: "project:<path>"|"topic:<path>"|"agent:<path>", path, kind, own: {enabled?, profile?},
                  enabled, profile, from: {enabled, profile} (owner that set it, "" = default), feature,
                  inherited: OwnerResolve of the parent|null (topic, agent), chain: [owner] (nearest first),
                  exit: ExitView|null (its profile's, not direct), project: "projects/<name>", project_profile:
                  pid|"" (not made yet), sites: [site]|null (a sandboxed agent's domains, the only sites its
                  browser opens; null = any public site), asks: [BrowserAsk] }
BrowserAsk      { id (16 hex), session, owner, profile, reason, what: "captcha"|"sign_in"|"code"|"payment"|"consent"|"other",
                  at, expires, status: "pending"|"done"|"skip"|"timeout"|"expired", note?, decided_at?, decided_by? }
BrowserAction   { at, session, nav, tool, args (values typed -> "<n chars>", urls without query), ok, ms?, page?, refused? }
```

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/browser` | – | the feature on: every project with an agent gets its profile first; `{feature, navigators: [Navigator], settings: BrowserSettings, available: {ok, missing}, tools: {tailscale, wireguard} (installed), setup: {running, log, error}, profiles: [ProfileRow], exits: [ExitView], direct: {test: ExitTest\|null, checking}, summary: Summary, asks: [BrowserAsk], waiting: [Waiting]}`; also checks in the background the exits not checked for 60 s and tests again (no speed) an up exit whose last good test is over 1 h old (`ExitView.checking` meanwhile) |
| PUT | `/api/browser/settings` | `Partial<BrowserSettings>` (other keys ignored) | same as GET (`400 bad_browser`) |
| POST | `/api/browser/setup` | `{exits?: bool}` | `{running: true}`; installs in the background (root): Chromium & co, `exits` = also Tailscale + wireproxy (pinned versions, checked hashes) into `<state>/tools/`; see `setup` in GET |
| POST | `/api/browser/profiles` | `{name, exit?, on_exit_down?}` | `BrowserProfile` (`400 bad_browser` no name / bad value / unknown exit, `409 too_many`) |
| GET | `/api/browser/profiles/{pid}` | – | `{profile: BrowserProfile, browser: BrowserState, gone, agents: [Navigator] (lasting, on it), person: [Navigator] (the person's when on it), temporary: [SessionLine] (newest first, open ones without journal first), actions: [BrowserAction] (30 newest), asks: [BrowserAsk]}` (`404 no_profile`) |
| PUT | `/api/browser/profiles/{pid}` | same as POST, every key optional | `BrowserProfile` (`400`, `404 no_profile`) |
| DELETE | `/api/browser/profiles/{pid}` | – | `{ok}`; stops it, erases its folder, tabs and journal; its agents go back to their project's (`404`, `409 main`, `409 project` while its project exists) |
| POST | `/api/browser/profiles/{pid}/open` | `{nav?}` (`me`) | `BrowserState` of that navigator; starts the profile for the person with a tab in it (its last one, else the first site of the list) (`400 bad_navigator`, `404 no_navigator`, `409 off`, `409 too_many_profiles`, `503 unavailable`, `404`) |
| POST | `/api/browser/profiles/{pid}/stop` | – | `BrowserState`; the profile sleeps (its tabs are kept, asleep) |
| POST | `/api/browser/profiles/{pid}/sleep` | – | `BrowserState` + `slept`: every tab not shown sleeps |
| POST | `/api/browser/profiles/{pid}/forget` | – | `BrowserState`; stopped, sign-ins, tabs and journal erased |
| GET | `/api/browser/profiles/{pid}/picture?nav=me&w=480` | – | JPEG (`no-store`) of the tab shown in that navigator, else its last used, `w` 160..960 px wide; `204` while the profile is not running (never starts it) (`404 no_profile`) |
| POST | `/api/browser/profiles/{pid}/files?nav=me` | multipart `files` (<= 20, 50 MB each) | `BrowserState`; given to the page of that navigator that asked (its file input, `chooser`), copied into the profile's uploads folder (`409 no_chooser`, `413 too_large`) |
| POST | `/api/browser/profiles/{pid}/tabs` | `{url?, nav?}` (`me`) | `BrowserState` of that navigator; a new tab of the person in it, in that navigator's window (`400 refused` for a page its rules refuse) |
| POST | `/api/browser/profiles/{pid}/tabs/{key}/show` | – | `BrowserState`; shows it, wakes an asleep one (`404 no_tab`) |
| DELETE | `/api/browser/profiles/{pid}/tabs/{key}` | – | `BrowserState` (show / close: of the tab's navigator) |
| PUT | `/api/browser/navigators/{nav}` | `{profile}` (`nav` = `me`) | `{id, name, profile, at}`; the person's browser on another profile: its tabs move there, asleep (`404 no_navigator`, `404 no_profile`) |
| POST | `/api/browser/exits` | `{type, name?, url?, user?, secret?, node?, login_server?}` | `ExitView`; the id is made from the name (`400 bad_exit` no type / bad url / bad login_server, `400 bad_secret`, `409 too_many`) |
| PUT | `/api/browser/exits/{eid}` | same, every key optional (`type` ignored) | `ExitView`; `secret` replaces the vault value; its runtime state is forgotten (`404 no_exit`) |
| DELETE | `/api/browser/exits/{eid}` | – | `{ok}`; vault key, unit and `<state>/browser/exits/<eid>/` removed (`404`, `409 in_use` while a profile uses it) |
| POST | `/api/browser/exits/{eid}/test` | – | `ExitTest` (`eid` = `direct`: the server's own address); an exit that cannot start = `{ok: false, error, at}`; updates its state (`404 no_exit`) |
| GET | `/api/browser/exits/{eid}/tailscale` | – | `{state: "needs_setup"\|"needs_login"\|"starting"\|"no_node"\|"node_offline"\|"up", backend, auth_url, account, nodes: [{id, name, dns, os, online, active}] (devices offering an exit node), node, error?}`; starts its `tailscaled` and, signed out, `tailscale up` for a sign-in address (`404 no_exit` not a Tailscale exit) |
| POST | `/api/browser/exits/{eid}/tailscale` | `{node?}` \| `{action: "login"\|"logout"}` | same as GET; `node`: use that device (`--exit-node`, LAN access off) and save it (`400 bad_node`) |
| GET | `/api/browser/owner?path=` | – | `OwnerView` (`400 bad_path`: not a project / topic / agent folder, `404 not_found`) |
| PUT | `/api/browser/owner` | `{path, enabled?, profile?, inherit?: ["enabled"\|"profile"]}` | `OwnerView`; `inherit` removes the owner's own key (`profile` = back to its project's); `profile` / `inherit: ["profile"]` for an agent only (`400 bad_browser`, `404 no_profile`) |
| POST | `/api/browser/waiting/{sid}` | `{action: "resume"\|"retry"\|"dismiss"}` | `resume` / `retry`: `{ok (the exit works now), waiting: Waiting\|null}` (`resume` = the turn goes on when the exit is back); `dismiss`: `{ok}` (`404 not_waiting`) |
| GET | `/api/browser/asks?session=&path=` | – | `{asks: [BrowserAsk]}` pending |
| POST | `/api/browser/asks/{id}` | `{action: "done"\|"skip", note?}` | `BrowserAsk` (`409 decided`); the person's hand is released. `done` stores the hand-back in the request file (never in the response): `trail` (pages the person went to in that session's tab, without query), `page`, `picture` (base64 JPEG): `ask_human` returns them to Claude (text + an image block) |
| POST | `/api/browser/live-token` | – | `{token}` one use, 30 s |
| WS | `/api/browser/live?t=<token>&profile=<pid>&nav=<navigator>&q=auto\|high\|low` | signed-in cookie + token | one navigator (default `me`) of a profile (default `main`; `4403` bad token / cookie, `4404` no profile). Server -> binary JPEG frames of the tab shown, text `{"t":"state", browser: BrowserState, me, asks}` (when it changes) / `{"t":"error", text}`. Client -> `{"t":"got"}` as each frame arrives (up to 3 are on their way per viewer, `live.INFLIGHT`; one the connection could not send yet is replaced by the newer one; quality adapts to the queueing measured), `{"t":"mouse", type: down\|up\|move, x, y (0..1), button?, clicks?, alt?, ctrl?, meta?, shift?}`, `{"t":"wheel", x, y, dx, dy}`, `{"t":"key", type: down\|up, key, code, keyCode, text?}`, `{"t":"text", text}`, `{"t":"nav", url}` (`rules.address`: not an address = a search with `settings.search`), `{"t":"back"\|"forward"\|"reload"}` (each one gives the person the tab shown), `{"t":"copy"}` -> `{"t":"copied", text}` (the page's selection), `{"t":"dialog", accept, text?}` (answers `dialog`), `{"t":"chooser"}` (no file for the page), `{"t":"take"}`, `{"t":"release", done?: true\|"skip", note?}`, `{"t":"quality", q}`, `{"t":"size", w, h, dpr?}` (CSS px of the view: the page in front is laid out for it, clamped 360x320..2560x1600; back to 1280x800 when nobody watches). `auto`: JPEG quality 30..70 follows the time a frame takes to reach the slowest viewer |
| POST | `/api/browser/mcp/{sid}` | JSON-RPC `tools/list` \| `tools/call` | loopback + `Authorization: Bearer <turn token>` only (`browser_mcp.py`); owner and profile come from the turn file; refusals, a down exit (after `exit_wait_s`) and `409 too_many_profiles` come back as `isError` tool results |
| WS | `/api/browser/cdp/{pid}` | – | loopback + `X-Browser-Secret` (one per turn) only: that turn's chrome-devtools-mcp to its profile's Chromium, filtered by `rules.json` and by its view (view.py) |

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

## Code (Changes view)

`maxxing/codediff.py` + `maxxing/api/code.py`. Before and after every turn (not plan mode, compact or hand-off) the
runner photographs the session's repositories (its folder's, the ones it changed before, the ones of the files Claude
wrote): working tree incl. untracked files (`.gitignore` respected) written through a throwaway index, kept as a
commit under `refs/maxxing/<sid8>/<n>/{pre,post}` (never pushed; deleted after 30 days or with the session by the
nightly maintenance). The user's index, HEAD and files are never touched. A turn that changed something appends
`mx_changes` `{n, repos:[{root, name, branch, pre, post, approx, files:[{path, old, status A|M|D|R|C|T, add, del,
binary}], more, add, del}]}` to the log, shown as the event `changes`. Session meta: `code_turn`, `code_repos` (≤ 8,
most recent first), `code_base` (`{root: first photo}`). `repo` = a repository's top folder inside the files root;
revisions = 7-40 hex digits, `HEAD` or `now` (a fresh photo). Reads run without the repository's hooks / filters /
fsmonitor (as `/api/git`); commit and push keep the repository's hooks. Errors as `/api/git` plus `404
repo_not_found|no_photo`, `400 bad_rev|bad_path|bad_scope|no_message|nothing|detached|bad_branch|same_branch|
not_github|no_base`, `403 no_write`, `409 running`.

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/sessions/{id}/changes?scope=turn&n=&base=` | – | `{scope, n, repos:[...]}` — `turn` (default: the last turn that changed something, or `n`): the `mx_changes` entry + live `branch, upstream, ahead, behind, remote`; `session` (first photo → now), `uncommitted` (HEAD → now), `branch` (merge-base with `base` or origin's default → now): one entry per known repository with changes (`error` when git failed) |
| GET | `/api/code/diff?repo=&a=&b=&path=&old=&full=` | – | `{path, hunks:[{head, o, n, lines:[{t: ' '\|'+'\|'-', o, n, s}]}], binary, cut, lines}` (≤ 2 000 lines unless `full`) |
| GET | `/api/code/commits?repo=&base=` | – | `[{sha, short, subject, author, at}]` (HEAD not in base, 100) |
| GET | `/api/code/status?repo=` | – | `{root, name, branch, upstream, ahead, behind, remote, dirty (files a commit would take), github, pr:{number, url, title, draft, base}\|null (open), merged_pr:{number, url, title, merged_at, head_sha, base}\|null (no open one: the last merged PR of the branch), checks:{total, ok, failed, pending}\|null, github_error?}`; `remote` = `remote.origin.url` as configured (no `insteadOf` rewrite) |
| POST | `/api/code/restore` | `{repo, source, paths?}` | `{undo, restored, removed}` — files back as in `source` (all that differ when no `paths`); `undo` = photo taken first |
| POST | `/api/code/undo` | `{repos:[{root, undo}]}` | `{repos:[...]}` — puts back what a restore / revert replaced |
| POST | `/api/sessions/{id}/revert` | `{n}` | `{n, repos:[{root, name, undo, restored, removed, commits_kept}]}` — every repository changed by turn `n` or later back to its photo from before (files only; `409 running` during a turn) |
| POST | `/api/code/commit` | `{repo, message, paths?, push}` | `{sha, branch, upstream, ahead, behind, ..., pushed?}` (`git add -A` of `paths` or everything) |
| POST | `/api/code/push` | `{repo}` | head info (sets the upstream `origin/<branch>` the first time) |
| POST | `/api/code/branch` | `{repo, name}` | head info (`git switch -c`) |
| POST | `/api/code/pr` | `{repo, title?, body?, base?, draft}` | `{number, url, title, state, draft}` — pushes first if needed; title = the only commit's subject (else the newest), body = the commits; a token that can write to the repository |
| POST | `/api/code/pr-text` | `{repo, session?, base?}` | `{title, body}` — written by the same small call from the session's conversation (what the user asked and the final answer of each turn, 24 kB, the newest kept), the branch's commits, the diff against `origin/<base>` (40 kB) and the repository's PR template; `502 no_message` when Claude fails |
| POST | `/api/code/message` | `{repo, a=HEAD, b=now}` | `{message}` — proposed by a small `claude -p` call (Haiku) from the diff (40 kB) and the 10 last subjects; `Co-Authored-By` lines dropped |

### Separate copies (worktrees)

`maxxing/worktrees.py`. Code mode only (`403 code_mode_off`). A session created with `worktree` gets a `git worktree`
of a clone of its topic in `<topic>/worktrees/<slug>` (`.worktrees/` when the topic folder is inside the repository;
then added to `.git/info/exclude`) on a new branch `<prefix>/<slug of the title>` (prefix `session` by default, per
repository) from `base` (default: origin's default branch). Its turns run there (`runner._cwd`), with a line of
`--append-system-prompt` naming the copy. The branch is renamed after the session's (short) title until it has an
upstream. Session meta `worktree = {path, repo, branch, base, base_ref, created, named, pr?, prepare?, env_copied?,
port, included?, removed?, kept_branch?}`; `Session.worktree` = `{path, repo, branch, base, pr, kept_branch, port, removed, preparing}`.
Per-repository preferences `{prefix, prepare, copy_env}` in `<state>/worktrees.json`; the preparation runs once in a
thread (15 min max), log `<state>/worktrees/<sid8>.log`. Errors: `400 not_here|bad_base|bad_prefix|is_pr|
no_local_base`, `404 no_copy`, `409 uncommitted|conflict|base_busy|branch_in_use|running|has_copy` (moving the
session). Deleting a session removes its copy when it is clean and its commits are in its base or pushed
(`worktrees.on_delete`). A pull request's local branch is only moved forward to `origin/<branch>`, never reset.
A `.worktreeinclude` at the root of the clone (gitignore syntax) names ignored files copied into every new copy
(`included` = how many; only files git ignores, no links, 500 files / 200 MB at most). Each copy owns ports
`port`..`port+9` (from 4100, blocks of 10 nothing listens on and no live copy owns): its turns and its preparation get
`MAXXING_PORT` (first port) and `MAXXING_COPY_PATH`, and Claude is told to use them.

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/code/copy-repos?path=` | – | `{enabled, repos:[{root, name, branch, branches, default_base, github, prefs:{prefix, prepare, copy_env}}]}` — the clones of the topic (or the repository holding it) |
| PUT | `/api/code/copy-prefs` | `{repo, prefix?, prepare?, copy_env?}` | the preferences |
| POST | `/api/sessions` | `{…, worktree:{repo, base?, prepare?, copy_env?, remember?}}` | Session (the copy is made before the first turn) |
| GET | `/api/sessions/{id}/copy` | – | `{path, repo, branch, base, pr, prepare, env_copied, included, port, exists, removed, ahead, behind (against the base), dirty, upstream, pushed_ahead, github, fork, watch}` |
| PUT | `/api/sessions/{id}/copy/watch` | `{on}` | `{watch}` — Claude watches the copy's PR (on by default; never a fork's or an outsider's PR) |
| POST | `/api/sessions/{id}/copy/merge` | `{message?}` | `{merged, base, sha, removed, kept_branch}` — commits first with `message`; merges the base into the branch in the copy (aborted on a conflict: `409 conflict`), then moves the base forward (fast-forward only) and removes the copy |
| POST | `/api/sessions/{id}/copy/remove` | `{force, merged_pr?}` | `{removed, kept_branch}` — `force` = discard (uncommitted files and the branch go); else refused with uncommitted files, and the branch is kept unless merged; `merged_pr`: its PR was merged on GitHub (looked up again: `409 not_merged` otherwise) - the branch goes when its tip is in the PR's head (squash / rebase merges too) |
| GET | `/api/sessions/{id}/copy/prepare-log` | – | `{log}` |
| GET | `/api/code/copies` | – | the copies still on disk: `[{sid, title, path, archived, …status}]` |
| POST | `/api/code/pr-session` | `{repo: "github:owner/name", number, review, message?, clone?}` | Session — in the topic of a local clone, on a copy of the PR's branch (a fork: `pr/<n>` from `refs/pull/<n>/head`); plan mode when `review` or when the author is outside (`author_association` not OWNER / MEMBER / COLLABORATOR). `400 no_clone` |

**The PR watch** (`maxxing/prwatch.py`, a loop of `api/code.py`, every 3 min; `MAXXING_PRWATCH_LOOP=0` turns it off):
for each session on a copy whose branch has an open PR (and `watch`), the new events - every check of the head ended
with a failure, a conflict with the base, a comment / review / line comment from OWNER / MEMBER / COLLABORATOR (never a
bot nor the server's own GitHub logins) - are sent to the session in one message, `source: "github"`, comments quoted
as data. Once per event (keys in `<state>/prwatch.json`), never while a turn runs, at most 4 messages per session in
24 h; what is there when the watch first sees the PR (or when it is turned back on) never wakes it. Comments are read
only when the PR's `updated_at` moves.

### Pull requests (GitHub)

`gitview.github_pull` and the actions. `repo` = `github:owner/name`; the token used is the first of the vault that
GitHub accepts (writes: one that can write, else `403 no_write`; GitHub refusing a merge: `409 refused`).

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/git/pulls?repo=&state=open` | – | `[{number, title, author, head, base, draft, url, updated, state: open\|closed\|merged, outside, review_me}]` (`state` open \| closed \| all, 30 most recently updated) |
| GET | `/api/git/pull?repo=&number=` | – | `{full, number, title, body, author:{login, avatar}, association, outside, state, draft, mergeable, mergeable_state, head, head_sha, head_repo, fork, base, url, created, updated, commits, add, del, files:[{path, old, status, add, del, hunks, binary, cut, lines}] (≤ 300), files_total, conversation:[{kind: comment\|review, id, author, body, state?, at, url}], line_comments:[{id, path, line, side, author, body, at, reply_to, outdated}], checks:[{name, status, conclusion, url}], methods, can_write, local_paths}` |
| POST | `/api/git/pull/comment` | `{repo, number, body}` | `{id, url}` |
| POST | `/api/git/pull/review` | `{repo, number, event: APPROVE\|REQUEST_CHANGES\|COMMENT, body, comments:[{path, line, side, body}]}` | `{id, state, url}` |
| POST | `/api/git/pull/merge` | `{repo, number, method: squash\|merge\|rebase, sha?}` | `{merged, sha, message}` |
| POST | `/api/git/pull/close` | `{repo, number}` | `{state}` |

A ` ```pr-review ` block in a message (`{"repo", "number", "event", "summary", "comments":[{path, line, body}]}`) is
drawn as a review card with **Publish on GitHub** (the review `POST` above, on the user's click). Text from GitHub
shown in the PR view never turns into such a card.

## Terminal

`maxxing/terminal.py` + `maxxing/api/term.py`. Config `code_mode` (default false; shown read-only by
`/api/settings`). A terminal = a login shell (`setsid -c $SHELL -l`) on a pseudo-terminal, child of the server: it
ends when closed, after 30 min without input or output, or when the service stops. 4 at most; the folder must be
inside the files root. Its output since the start (last 256 KB) is replayed to every new connection. Never for agents
(the web app only offers it in normal sessions). Errors: `403 term_off|bad_token`, `400 bad_cwd`, `404 not_found`,
`409 too_many`, `401 bad_password` / `429 throttled` (enable).

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/term` | – | `{enabled, terms:[{id, cwd, title, started, last, alive, clients}], max}` |
| POST | `/api/term/enable` | `{password}` | `{enabled:true}` — the current password again (same throttle as a password change) |
| POST | `/api/term/disable` | – | `{enabled:false, closed}` — closes every terminal |
| POST | `/api/term` | `{cwd, cols?, rows?}` | `{…term, token}` — opens one; `token` = one-time websocket token (30 s) |
| POST | `/api/term/{tid}/token` | – | `{token}` — a new one-time token (reconnection, page reload) |
| DELETE | `/api/term/{tid}` | – | `{ok}` |
| WS | `/api/term/{tid}/ws?token=` | session cookie, same `Origin` as `Host` | server → browser: binary output frames; browser → server: text JSON `{"i": input}` or `{"r": [cols, rows]}` · close `4401` (cookie / origin), `4403` (token), `4000` (the shell ended) |

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
| POST | `/api/mail/{id}/attachments/view` | `{folder, uid, indexes: [int]}` (≤ 100) | `{paths: {index: path}}`: copies of those attachments (one IMAP fetch) under `<workspace>/mail/attachments/<id>/<folder hash>-<uid>/<index>/<name>` for the file viewer, rewritten at each view, copies older than a day removed (`attachments`: out of the memory backup) · `404 not_found` · `409 outside` (workspace outside the files root: the UI downloads instead) |
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
| POST | `/api/team/chats/{cid}/summarize` | `{ids?, since?}` | Message `kind: summary` (`ids` = the chosen messages, else after `since`, else after the last summary; at most `SUMMARY_CHARS` = 100,000 characters sent, the oldest left out) · `409 busy` (a summary of this chat is running) |
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
| ANY | `/api/ext/{id}[/{path}]` | – | forwarded to the extension's `api.py` `handle()`: return value → JSON, `(status, body)` tuple sets the status (an int from 200 to 599, else 500 `extension_error`; 204 / 304 are sent without a body), `ValueError` → 400, `LookupError` → 404, other → 500 `extension_error`, 30 s timeout (504 `extension_timeout`), 503 `extension_busy` at once while an earlier timed-out `handle()` of the same extension has not returned, or when the 4 extension threads are all still running earlier calls. A `.` / `..` segment in `path` → `400 bad_path` |
| GET | `/ext/{id}/page.js` | – | page module (ES module) |
| GET | `/ext/ui-kit.css` | – | the UI kit of extensions (`server/maxxing/assets/ui-kit.css`): `ui-*` classes scoped to `.mx-ext` (page host) and `[data-mx-kit]` (widget frame), built on the theme variables; the app adds it once when a page extension opens; `ETag` (content hash), `If-None-Match` -> `304` |
| GET | `/ext/{id}/widget-frame` | – | HTML widget document: the bridge (`maxxing.api / resize / theme`, theme, material and variables from the URL fragment, then by message; `<html data-theme data-material>`) + the UI kit inlined (`<html data-mx-kit>`) + `widget.html`, `Content-Security-Policy: sandbox allow-scripts allow-pointer-lock` (the UI frames it with the same sandbox; an srcdoc frame would inherit the app's script policy). `/ext/{id}/widget.html` stays the raw file (text/plain) |
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
| GET | `/api/memory` | – | `{max_lines, max_bytes (the weight that goes with the line limit: 1 KB for 10 lines, 0 = no limit), files:[{path (workspace-relative), level:"global"\|"project"\|"topic"\|"agent", lines, bytes, over:bool (above the limit, in lines or in weight), heavy:bool (in weight)}]}` |
| POST | `/api/memory/compact` | – | `{session: Session}` — a session at the workspace root runs the memory-compaction skill now with the limit (lines and weight) |

## Push (Web Push, Settings -> Alerts -> Mobile notifications)

Web Push (VAPID) with no dependency: ES256 on P-256 in pure Python (`webpush.py`, checked against the RFC 6979 vector) and **empty** pushes - nothing of the conversation goes through the browser vendor's push service. The service worker is woken, then asks `POST /api/push/pending` (same origin, the app's cookie + `X-Maxxing: 1`) what to show. State: `webpush.json` in the state dir (mode 0600: VAPID key pair + devices); the queue of what a device has not fetched yet is in memory (20 items, 24 h). Endpoints are only accepted for the browsers' push services (https, `fcm.googleapis.com`, `*.push.services.mozilla.com`, `web.push.apple.com`, `*.notify.windows.com`), so the server never calls another address. A turn rings every device when a person's session ends (same rule as the Telegram bell: not a job, an agent, a Telegram or a system turn; failed turns too); `404` / `410` from the push service remove the device.

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/push/key` | – | `{key}`: the application server key (uncompressed P-256 point, base64url) to subscribe with |
| GET | `/api/push/devices` | – | `[{id, label, at}]` (`id` = first 16 hex digits of the SHA-256 of the endpoint) |
| POST | `/api/push/devices` | `{endpoint, label?}` | `{id, label}` (registers or refreshes) · `400 bad_endpoint` (not a known push service, or 20 devices) |
| DELETE | `/api/push/devices/{id}` | – | `{ok: true}` · `404` |
| POST | `/api/push/test` | – | `{sent}`: devices woken with a test notification |
| POST | `/api/push/pending` | `{device}` | `{items: [{title, body, url, tag}]}`: what the woken device shows, then forgets (`[]` for an unknown device) |

## Stats

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/stats/tokens?force=1` | – | `{totals, projects:[{name, …}], topics:[{path, label ("acme / blog", "acme / blog / Writer" for an agent folder), agent (display name or null), …}], sessions:[{id, title, path, archived, updated, …}] (top 100), days:[{date, tokens, cost_usd}] (90 days), latency:{start_s, first_answer_s, turns}, at}` (latency: medians over the last 20 turns of every session: seconds from starting `claude` to its first event / first answer); each group has `input, output, cache_read, cache_write, total, cost_usd, turns, sessions` (sorted by `total`; project `""` = workspace root). Cached 20 s |
| GET | `/api/stats/budget` | – | the server's daily budget: `{usd_per_day (settings `daily_budget_usd`, 0 = none), spent_today ($ of today in the Harness time zone, every session, job and agent), reached:bool}`. Once reached, scheduled prompt jobs and agent triggers wait for the next day (run `skipped`, reason `limit`); the user's own messages and "Run now" still run. Notifications: one at 80 %, an alert when reached (ref `budget:reached`, closed when work runs again) |

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
| GET | `/api/feed?source=&unread=1&pending=1&before=<id>&limit=50` | – | `{events: FeedEvent[], more, unread, unread_errors, pending, sources: [{source, total, unread, unread_errors}]}` newest first (`unread_errors`: the unread ones of level `error`: the Home badge turns red) (`limit` <= 200); `pending=1` = only the alerts still waiting (a request until decided, any other alert until read); `pending` = how many wait |
| POST | `/api/feed/{id}/act/{action}` | – | `{event}` after the action: `allow` / `deny` (an agent's request, as `POST /api/approvals/{id}`), `seen` (read; a health issue is marked seen), `open` (read). **Idempotent**: on a resolved event any action returns it unchanged (the same answer for a second click, web or Telegram) · `400 bad_action`, `404 not_found` |
| POST | `/api/feed` | `{title, body?, level?, source?, url?, dedupe?, group?}` | `{event, duplicate}` (`dedupe` = idempotent per source; `group` folds into the latest unread row of that group, 24 h) · `400 empty\|bad_level\|bad_source` |
| POST | `/api/feed/read` | `{ids?: number[], source?, all?: bool}` | `{unread}` |
| DELETE | `/api/feed/{id}` | – | `{ok}` |
| GET / PUT | `/api/feed/settings` | PUT `{telegram?: bool, health?: bool, rules?: {<source>: "auto"\|"off"\|"silent"\|"loud"}}` (merged; at most 200 non-auto rules, else `400 too_many_rules`) | `{telegram, health, sources: [{source, label, builtin, rule, own_thread}], hooks: FeedHook[], kinds, rules}`; `health` = config `health_feed` (server health problems as alerts; `maxxing init`: on for a new install, off for an older one) |
| POST | `/api/feed/hooks` | `{name, kind: "stripe"\|"shopify"\|"github"\|"generic", secret?}` | `FeedHook = {id, name, kind, created, url, has_secret}` · `409 exists\|reserved`, `400 bad_kind` |
| PATCH | `/api/feed/hooks/{id}` | `{secret?, regenerate?: bool}` | `FeedHook` (regenerate = new token, the old URL dies) |
| DELETE | `/api/feed/hooks/{id}` | – | `{ok}` |
| POST | `/api/feed/hooks/{id}/test` | – | `{event}` |
| POST | `/api/hooks/{token}` | the service's payload (<= 1 MB) | (a token of Settings -> Webhooks: see Webhooks & events) **public** (no cookie, no CSRF header: the token is the permission). Signatures: Stripe `Stripe-Signature` (5 min tolerance), Shopify `X-Shopify-Hmac-Sha256`, GitHub `X-Hub-Signature-256`, generic `X-Signature: sha256=<hex>` - checked when the hook has a secret; a stripe/shopify/github hook WITHOUT a secret refuses every delivery with `401 secret_required` (+ one folded `security` warning in the feed); a generic hook without a secret accepts the token alone. `200 {ok, duplicate, id}` / `{ok, ignored}` (a delivery verified with a secret whose body was already received is a duplicate whatever its unsigned headers, even if it was ignored or its event deleted: 30 days, generic 24 h; Shopify keys a known topic too) · `401 bad_signature\|secret_required`, `404` (unknown token: checked before the body is read), `413` (Content-Length or streamed body over 1 MB), `429` (120/min/hook), `400 bad_json` (also for JSON nested too deep), `400 bad_payload` (valid JSON whose fields have an unexpected shape for that service) |

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
| GET | `/api/skills?path=projects/<p>/topics/<t>` | - | `{skills: Skill[]}`: only those a session of that topic sees (product, user, workspace, its project, the topic itself): the composer's `/` menu |

## Jarvis

Settings -> Features -> `jarvis_feature` (off by default; `PUT /api/settings`). One assistant whose conversation is a
session of the hidden topic `projects/jarvis/topics/main` (server `jarvis.py`). Bus topic `jarvis`.

| Method | Path | Body | Answer |
|---|---|---|---|
| GET | `/api/jarvis` | | `JarvisStatus` |
| POST | `/api/jarvis/open` | | its conversation, made the first time (409 `off`; 409 `taken`: an owner's project named `jarvis`) -> `JarvisStatus` |
| POST | `/api/jarvis/new` | | a new conversation (the old one is kept in `conversations`) -> `JarvisStatus` |
| PUT | `/api/jarvis/settings` | any of `model`, `root`, `ask_first`, `internals`, `daily` (bool), `brief`, `dream` (`HH:MM` or ""), `compact_tokens` (0 = as every session, 100000, 150000, 200000, 300000), `telegram` (`off`, `important`: brief, questions and failures, `all`), `reuse`, `archive_done` (bool) | `JarvisStatus` (400 `bad_time`, `bad_compact`, `bad_telegram`) |
| POST | `/api/jarvis/work/{ref}/close` | | `ref` = the entry's number or its session id -> `JarvisStatus` |
| POST | `/api/jarvis/brief` | | the morning brief now (a new conversation with `daily`; its backstage agent prepares it, then it comes in as a `[Morning brief]` message) -> `JarvisStatus` |
| POST | `/api/jarvis/dream` | | the night pass now: `{session}` (a run of its backstage agent `<path>/agents/backstage`; 409 `agent` when it cannot start) |

`JarvisStatus` = `{on, path, session: Session | null, settings, last_brief, last_dream, work: JarvisWork[] (newest
first, 100), open, asks, conversations: [{id, title, updated, state, current}]}`. `JarvisWork` = `{id, session, path,
title, brief, state: running | replied | failed | closed, created, updated, result, cost, question, turns}`.
While `internals` is off, `GET /api/workspace/tree`, `GET /api/sessions` (without `path`) and `GET /api/search` leave
Jarvis's project out; `POST /api/workspace/projects` refuses the name `jarvis` (409 `reserved`).

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
