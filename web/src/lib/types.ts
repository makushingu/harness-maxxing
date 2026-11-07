// TypeScript mirror of docs/dev/API.md. Keep in sync with the contract (change API.md first).
// Timestamps are Unix seconds (float).
import type { Look } from '@/stores/ui'

export type Ok = { ok: boolean }
export type Language = 'en' | 'fr'
export type Tone = 'ok' | 'warn' | 'error'

/* ---------------------------------------------------------------- Errors */
export type ApiErrorBody = { error: string; message?: string }

/* ---------------------------------------------------------------- Auth & setup */
export type AuthState = {
  setup_required: boolean
  authenticated: boolean
  version: string
  onboarding_completed: boolean
  language: Language
  /** Look last chosen in a signed-in browser (null: never): the sign-in page shows it. */
  look: Look | null
}
export type SetupBody = { token: string; password: string }
export type LoginBody = { password: string }
/** A sign-in (or turning two-step sign-in on) waiting for an approval in Telegram. */
export type TwoFactorChallenge = { challenge: string; expires_in: number }
export type LoginResult = { ok: boolean; two_factor?: TwoFactorChallenge }
export type TwoFactorPoll = { ok: boolean; status: 'pending' | 'approved'; expires_in?: number }
export type ChangePasswordBody = { current: string; new: string }

/* ---------------------------------------------------------------- Onboarding */
export type OnboardingStepKey = 'password' | 'claude' | 'workspace' | 'telegram' | 'backup' | 'profile'
export type OnboardingState = { completed: boolean; steps: Record<OnboardingStepKey, boolean> }

/* ---------------------------------------------------------------- Claude */
export type ClaudeAuthMethod = 'oauth_token' | 'credentials' | 'api_key' | null
export type PermissionMode = 'bypass' | 'acceptEdits' | 'default'
export type ClaudeModel = { id: string; label: string; /** Last context window Claude Code reported for this model here. */ context_window?: number | null }
export type ClaudeStatus = {
  installed: boolean
  version: string | null
  /** `ok` reflects the last REAL call (turn / test / background check); `checked_at` null = not verified yet. */
  auth: { ok: boolean; method: ClaudeAuthMethod; detail: string | null; checked_at?: number | null; error?: string | null }
  default_model: string
  permission_mode: PermissionMode
  /** A turn ending above this context (tokens) is followed by an automatic compaction; 0 = off. */
  auto_compact_tokens: number
  /** A message that comes back to a session idle for more than `idle_compact_after_s` with at least this context
   *  is preceded by a summary turn (the prompt cache expired anyway); 0 = off. */
  idle_compact_tokens: number
  idle_compact_after_s: number
  /** A user message after a pause of 5 min+ to a session with at least this context (cache expired, or 100k+) is
   *  sorted by a small model call: new subject -> summary first, follow-up -> the thread goes on; 0 = off. */
  smart_resume_tokens: number
  protect_secrets?: boolean
  /** New sessions get a short title (2-5 words) naming their subject. */
  short_titles?: boolean
  short_titles_model?: boolean
  /** Claude Code updated by the server while nothing runs (`claude_auto_update`, default on). */
  auto_update?: ClaudeAutoUpdate
  models: ClaudeModel[]
}
export type ClaudeAutoUpdate = {
  enabled: boolean
  checked_at: number | null
  latest: string | null
  last: { from: string; to: string; at: number; ok: boolean; error: string | null } | null
}
export type ClaudeAuthBody = { kind: 'oauth_token' | 'api_key'; value: string }
export type ClaudeAuthResult = { ok: boolean; error?: string }
export type ClaudeTestResult = { ok: boolean; model: string; ms: number; error?: string }
export type ClaudeSettingsBody = { default_model?: string; permission_mode?: PermissionMode; auto_compact_tokens?: number; idle_compact_tokens?: number; idle_compact_after_s?: number; smart_resume_tokens?: number; protect_secrets?: boolean; short_titles?: boolean; short_titles_model?: boolean; claude_auto_update?: boolean }

/* ---------------------------------------------------------------- Workspace */
export type Topic = {
  name: string
  project: string
  path: string
  description: string
  session_count: number
  /** Archived sessions of the topic (not in session_count): the tree's archived fold, before its list is loaded. */
  archived_count?: number
  running: number
  unread: number
  telegram_thread: number | null
  /** The topic's own permission mode for Claude turns; '' = the global setting. */
  permission_mode?: '' | PermissionMode
  /** Agents of the topic (Settings -> Features -> agents_page), without their status fields. */
  agents?: Agent[]
}
export type Project = { name: string; path: string; description: string; /** "" when none. */ emoji: string; topics: Topic[]; session_count: number }
export type WorkspaceTree = { root: string; projects: Project[] }

/* ---------------------------------------------------------------- Agents (Settings -> Features -> agents_page) */
/** The pixel character of an agent: `color` = outfit (one of the accent colours, tells projects apart). */
export type AgentAvatar = { color: string; skin: string; hair: string; hair_color: string; face: string; accessory: string }
export type AgentAvatarOptions = Record<keyof AgentAvatar, string[]>
export type AgentLimits = { usd_per_day: number; runs_per_hour: number; timeout_s: number; debounce_s: number }
export type AgentTrigger = { id: string; kind: 'feed'; enabled: boolean; source: string; levels: FeedLevel[]; match: string; prompt: string; hook_id?: string }
export type AgentTriggerInput = Partial<Omit<AgentTrigger, 'kind'>> & { kind?: 'feed' }
export type AgentThreadKind = 'note' | 'run' | 'result' | 'skip' | 'approval'
export type AgentMessage = { id: string; at: number; kind: AgentThreadKind; text: string; trigger?: string; source?: string; session?: string; ok?: boolean; cost?: number; reason?: string; /** run: the thread message it answers (its session went on) */ reply_to?: string; /** approval / its note: the request id */ approval?: string; /** note of an approval: allow, deny, timeout, expired */ status?: string; /** run: the files sent with it (absolute paths) */ attachments?: string[] }
export type AgentRuleTool = 'Bash' | 'Write' | 'Edit' | 'WebFetch' | '*'
/** "Refuse <tool> when it contains <match>", `reason` shown to Claude. */
export type AgentRule = { tool: AgentRuleTool; match: string; reason: string }
/** GET /api/agents/sandbox: what the sandbox needs on this server (missing among bwrap, socat, apparmor, linux). */
export type AgentSandboxStatus = { ok: boolean; missing: string[] }
/** POST /api/agents/import: the agent made from a Claude Code agent file; `ignored` = its fields with no equivalent. */
export type AgentImportResult = Agent & { ignored: string[] }
/** An agent = a folder projects/<p>/topics/<t>/agents/<name>/ (CLAUDE.md = its role, memory.md, agent.json). */
export type Agent = {
  /** projects/<p>/topics/<t>/agents/<name>: also a session path */
  path: string
  project: string
  topic: string
  /** folder slug */
  name: string
  display_name: string
  /** the role (first paragraph of its CLAUDE.md) */
  description: string
  avatar: AgentAvatar
  enabled: boolean
  model: string
  permission_mode: '' | PermissionMode
  allowed_tools: string[]
  disallowed_tools: string[]
  telegram: boolean
  approvals: boolean
  /** runs started by outside text (webhooks, feed, other agents) act per its mode instead of always asking first */
  trust_outside: boolean
  /** the Keys vault entries its turns see (none by default) */
  keys: string[]
  /** its commands write only in its folder (+ `writable`), cannot read the server's secrets, reach only `domains`;
   *  its runs never use bypass (bypass becomes acceptEdits). New agents: on. */
  sandbox: boolean
  /** agent.json cannot be read: switched off and sandboxed until the file is fixed (saves refused) */
  broken?: boolean
  /** hosts its shell commands may reach (sandbox), e.g. api.github.com, *.example.com */
  domains: string[]
  /** folders of the topic it may write in besides its own (`.` = the whole topic) */
  writable: string[]
  /** tool calls refused when they contain a text (max 20) */
  rules: AgentRule[]
  /** callable by Claude as a subagent from the normal sessions of its topic */
  subagent: boolean
  limits: AgentLimits
  triggers: AgentTrigger[]
  /** mailboxes of the E-mail page it may use (none by default) */
  mail?: MailGrant[]
  created: number
  session_count: number
  archived_count: number
  running: number
  unread: number
  /** Status fields: GET /api/agents and GET /api/agents/{path} only (not in the workspace tree). */
  cost_today?: number
  runs_last_hour?: number
  last_run?: AgentMessage | null
  running_now?: number
  running_sessions?: { id: string; title: string; started?: number }[]
  /** results posted after the user last opened the agent */
  thread_unread?: number
  /** approval requests of its running sessions */
  waiting?: number
  /** its other open, unread alerts in the Notifications (failed run, budget, runs per hour, broken trigger) */
  alerts?: number
}
/** A ready-made agent of the gallery (GET /api/agents/templates): fills the creation form. */
export type AgentTemplate = {
  id: string
  name: string
  summary: string
  /** its role (CLAUDE.md) */
  role: string
  /** what the user still has to connect */
  needs: string
  avatar: AgentAvatar
  permission_mode: PermissionMode
  approvals: boolean
  allowed_tools: string[]
  /** keys worth giving it; keys_present = the ones the vault holds */
  keys: string[]
  keys_present: string[]
  limits: Partial<AgentLimits>
  cron?: { schedule: string; prompt: string }
  webhook?: { kind: AgentWebhookKind; prompt: string }
  /** made for a mailbox of the E-mail page: the user picks which one when creating it */
  mail?: Omit<MailGrantInput, 'account'>
}
export type AgentHook = { id: string; name: string; kind: AgentWebhookKind; url: string; has_secret: boolean }
export type AgentDetail = Agent & { crons: Cron[]; webhooks?: AgentHook[]; trigger_stats?: Record<string, { events: number; last_event_at: number | null }> }
export type AgentsPayload = { agents: Agent[]; avatar: AgentAvatarOptions }
/** A member of an agent group (an agent of the group's project). `handle` = its @name in the group: its folder name,
 *  or made from its display name when two members share a folder name (`slug` = the same, older name). */
export type AgentGroupMember = {
  path: string
  handle: string
  slug: string
  /** one line: what it does in this group */
  role: string
  /** false: the agent was deleted (it no longer speaks) */
  exists: boolean
  display_name: string
  avatar: AgentAvatar
  enabled: boolean
  /** "stop @slug" or the pause button: it does not speak until named again */
  paused: boolean
  /** its turn is in progress */
  speaking: boolean
}
export type AgentGroupLimits = { waves: number; replies: number; per_hour: number }
/** An agent group = a folder projects/<p>/groups/<g>/ (CLAUDE.md = its goal, group.json, files/ = the shared folder).
 *  Only the owner writes; the members answer in turn and hand over with @slug. */
export type AgentGroup = {
  /** projects/<p>/groups/<g> */
  path: string
  project: string
  /** folder slug */
  name: string
  display_name: string
  /** "" when none */
  emoji: string
  goal: string
  members: AgentGroupMember[]
  /** member path ("" = none: the last one who spoke, else the first member) */
  lead: string
  shared_files: boolean
  trust_members: boolean
  limits: AgentGroupLimits
  created: number
  /** projects/<p>/groups/<g>/files, "" when the shared folder is off */
  files_path: string
  /** a turn in progress or members waiting their turn */
  busy: boolean
  /** the member path speaking now, "" */
  speaking: string
  /** the session of the turn in progress, "" */
  speaking_session: string
  last_at: number
  /** 1: a member spoke since the owner last opened the group */
  unread: number
}
/** One line of a group's conversation. kind: message (author "me" or a member path), pass (it had nothing to add),
 *  skip (a member could not speak: `reason`), note / stop (system lines, author ""). */
export type AgentGroupMessage = {
  id: string
  at: number
  kind: 'message' | 'pass' | 'skip' | 'note' | 'stop'
  author: string
  text: string
  session?: string
  cost?: number | null
  reason?: string
  /** note: the limit reached (waves, replies, per_hour) */
  limit?: string
  /** note: "New topic" (the members start fresh sessions) */
  reset?: boolean
  /** the owner's message: the files sent with it (absolute paths) */
  attachments?: string[]
}
export type AgentGroupInput = {
  /** create only */
  project?: string
  /** create only: the folder slug */
  name?: string
  display_name?: string
  emoji?: string
  goal?: string
  members?: { path: string; role: string }[]
  lead?: string
  shared_files?: boolean
  trust_members?: boolean
  limits?: Partial<AgentGroupLimits>
}
/** The order and colours picked by hand on the Agents page (GET/PUT /api/agents/layout), the same on every device. */
export type AgentsLayout = { projects: string[]; colors: Record<string, string>; agents: Record<string, string[]> }
export type AgentInput = {
  topic_path?: string
  name?: string
  /** Create only: the ready-made agent it starts from; the server applies its settings (domains, writable...) under the form's. */
  template?: string
  display_name?: string
  description?: string
  avatar?: Partial<AgentAvatar>
  enabled?: boolean
  model?: string
  permission_mode?: '' | PermissionMode
  allowed_tools?: string[]
  disallowed_tools?: string[]
  telegram?: boolean
  approvals?: boolean
  trust_outside?: boolean
  keys?: string[]
  sandbox?: boolean
  domains?: string[]
  writable?: string[]
  rules?: AgentRule[]
  subagent?: boolean
  limits?: Partial<AgentLimits>
  triggers?: AgentTriggerInput[]
  mail?: MailGrantInput[]
}
export type AgentRunResult = { started: boolean; /** the new session (its id in older answers) */ session?: Session | string; reason?: string; /** a reply: the session of that message went on */ continued?: boolean }
export type AgentWebhookKind = 'generic' | 'stripe' | 'shopify' | 'github'
export type AgentWebhookResult = { agent: AgentDetail; hook: { id: string; name: string; kind: AgentWebhookKind; url: string; has_secret: boolean } }
export type NameBody = { name: string; description?: string }
export type PatchNameBody = { name?: string; description?: string; /** Projects only; "" removes it. */ emoji?: string; /** Topics only; "" = the global setting. */ permission_mode?: '' | PermissionMode }

/* ---------------------------------------------------------------- Sessions */
export type SessionState = 'idle' | 'running' | 'error'
export type SessionSource = 'web' | 'telegram' | 'cron' | 'agent'
export type QueueItem = { text: string; attachments: number; source: 'web' | 'telegram' | 'cron' | 'system' | string; kind: string; /** A voice message sent directly (transcribed before its turn). */ voice?: boolean; client_ids?: string[] }
/** A message sent but not in the log yet (held at the head while a summary runs first, or its turn starting). */
export type SentItem = { text: string; attachments: string[]; source: string; voice?: string[]; client_ids?: string[] }
export type Session = {
  id: string
  title: string
  path: string
  state: SessionState
  queue: number
  /** The waiting messages, in order (text cut at 280 chars), whoever queued them. */
  queue_items?: QueueItem[]
  /** Messages already sent that the log does not have yet: the thread shows them as sent (text cut at 4000 chars). */
  sent_items?: SentItem[]
  created: number
  updated: number
  turns: number
  cost_usd: number
  model: string
  real_model: string | null
  context_tokens: number | null
  /** Context window of the last turn's model (e.g. 1 000 000); null when unknown. */
  context_window: number | null
  archived: boolean
  /** Pinned in the Favorites block of the sessions list (stored on the server: same on every device). */
  favorite: boolean
  notify: boolean
  source: SessionSource
  unread: boolean
  last_text: string
  error: string | null
  /** Plan mode: read-only turns ending with a plan the user validates before anything changes. */
  plan_mode: boolean
  /** A plan-mode turn finished: its plan waits for the user's validation. */
  plan_ready: boolean
  /** Tool calls waiting for the user's Allow / Deny (an agent with approvals; GET /api/approvals?session=). */
  approvals?: number
}
/** A tool call an agent waits on (agents with `approvals`): Allow / Deny in the session. */
export type Approval = {
  id: string
  session: string
  agent_path: string
  tool: string
  /** The tool's input, long strings clipped, secrets redacted. */
  input: Record<string, unknown>
  /** One line: "Bash: git push". */
  summary: string
  at: number
  expires: number | null
  status: 'pending' | 'allow' | 'deny' | 'timeout' | 'expired'
  message: string
  decided_at: number | null
  /** The input was too long to keep whole: only Deny (the server refuses Allow). */
  clipped?: boolean
}
export type CreateSessionBody = { path: string; message?: string; title?: string; model?: string; attachments?: string[]; plan_mode?: boolean; /** Absolute path of a voice message sent directly. */ voice?: string; /** This page's id for the first message (see SendMessageBody). */ client_id?: string }
export type PatchSessionBody = { title?: string; model?: string; archived?: boolean; notify?: boolean; plan_mode?: boolean; favorite?: boolean; /** Move to another topic (idle sessions only). */ path?: string }
export type SendMessageBody = { text: string; attachments?: string[]; hud?: boolean; /** Absolute path of a voice message sent directly: the server transcribes it, then sends it. */ voice?: string; /** This page's id for the message, found again in `client_ids` of its queue item and its log event (a reload mid-send checks it). */ client_id?: string }
export type SendMessageResult = { queued: boolean; session: Session }
export type SessionSearchHit = { id: string; title: string; path: string; snippet: string; at: number }
export type SearchKind = 'session' | 'file' | 'memory' | 'task' | 'group'
/** Full-text hit: `snippet` marks the matched words with \u0002 … \u0003. */
export type SearchHit = { kind: SearchKind; id: string; path: string; title: string; snippet: string; at: number | null; score: number }
export type SearchResult = { results: SearchHit[]; took_ms: number }
export type Upload = { path: string; name: string; size: number; mime: string }
export type UploadResult = { files: Upload[] }

export type Usage = { input: number; output: number; cache_read: number; cache_write: number }
export type SessionEvent =
  | { type: 'user'; text: string; attachments: string[]; at: number; source: SessionSource; /** Audio of a voice message sent directly. */ voice?: string[]; /** The web pages' ids of the message(s) it carries (SendMessageBody.client_id). */ client_ids?: string[] }
  /** Transcript of the voice message just above (or why it failed). */
  | { type: 'voice_text'; text: string; error: string | null; stopped?: boolean; at: number }
  | { type: 'assistant'; text: string; at: number }
  | { type: 'thinking'; text: string; at: number }
  | { type: 'tool_use'; id: string; name: string; input: unknown; input_lines?: Record<string, number>; summary: string; at: number }
  | { type: 'tool_result'; tool_use_id: string; text: string; is_error: boolean; at: number }
  | { type: 'init'; model: string; cwd: string; at: number }
  | { type: 'result'; ok: boolean; cost_usd: number; duration_ms: number; model: string; usage: Usage; at: number }
  | { type: 'note'; text: string; level: 'info' | 'warn' | 'error'; at: number }
  /** `ref` = `at` of a user event: hidden from the thread (or shown again). */
  | { type: 'hide'; ref: number; hidden: boolean; at: number }
  /** Background work of Claude Code (a sub-agent, a command): a partial update merged on `id`. */
  | TaskEvent
export type TaskState = 'running' | 'completed' | 'failed' | 'stopped'
export type TaskEvent = {
  type: 'task'
  id: string
  /** The Agent / Bash call that started it. */
  tool_use_id?: string
  at: number
  state?: TaskState
  kind?: 'agent' | 'shell' | 'other'
  background?: boolean
  description?: string
  agent_type?: string
  /** What it is doing now ("Running npm test…") and with which tool. */
  activity?: string
  last_tool?: string
  tokens?: number
  tools?: number
  duration_ms?: number
  /** The agent's final report (or the command's description). */
  summary?: string
}
export type SessionEventsPage = { events: SessionEvent[]; next: number; state: SessionState }
/** `?tail=N` / `?before=<offset>&limit=N`: backward pages (`start` = offset of the first line read). */
export type SessionEventsBackPage = {
  events: SessionEvent[]
  start: number
  next: number
  more_before: boolean
  state: SessionState
  reset?: boolean
}
/** SSE payloads of /api/sessions/{id}/stream */
export type SessionStreamEvents = { events: SessionEvent[]; next: number }

/* ---------------------------------------------------------------- Global bus */
export type BusTopic = 'agents' | 'agents_layout' | 'agent-groups' | 'sessions' | 'workspace' | 'tasks' | 'crons' | 'telegram' | 'backup' | 'health' | 'extensions' | 'trash' | 'feed' | 'profile' | 'register' | 'license' | 'infra' | 'mcp' | 'team' | 'team_live' | 'approvals'

/* ---------------------------------------------------------------- MCP servers (Settings -> MCP) */
export type McpState = 'connected' | 'needs_auth' | 'failed' | 'pending' | 'unknown'
export type McpServer = {
  id: string
  name: string
  scope: 'user' | 'local' | 'project'
  where: { rel: string | null; project: string | null; topic: string | null; exists: boolean; path: string | null }
  type: 'http' | 'sse' | 'stdio' | string
  url?: string
  command?: string
  args?: string[]
  headers?: Record<string, string>
  env?: Record<string, string>
  /** A token written in clear in the config (shown as •••): better in the Keys vault. */
  literal_secret: boolean
  /** Vault keys referenced as ${KEY}. */
  keys: string[]
  state: McpState
  detail: string | null
  approved?: boolean
}
export type McpView = { servers: McpServer[]; checking: boolean; checked_at: number | null; config_file: string; /** config `mcp_auto`: each turn loads only the servers its session needs */ auto?: boolean }
export type McpAddBody = { name: string; where: string; type: 'http' | 'sse' | 'stdio'; url?: string; command?: string; headers?: Record<string, string>; env?: Record<string, string> }

/* ---------------------------------------------------------------- Notifications feed */
export type FeedLevel = 'info' | 'success' | 'warning' | 'error'
/** A button of an event: `open` follows its link, the others go to POST /api/feed/{id}/act/{id} (`seen`, `allow`, `deny`). */
export type FeedAction = { id: string; label: string; style: 'primary' | 'danger' | 'default' | 'link' }
export type FeedEvent = {
  id: number
  at: number
  source: string
  level: FeedLevel
  title: string
  body: string
  url: string
  count: number
  read: boolean
  /** Alerts (an agent's request, a server problem...): buttons, what it follows, the agent it is about, how it ended. */
  actions?: FeedAction[]
  ref?: string | null
  agent?: string | null
  resolved?: number | null
  resolution?: string
}
export type FeedList = { events: FeedEvent[]; more: boolean; unread: number; pending?: number; sources: { source: string; total: number; unread: number }[] }
export type FeedRule = 'auto' | 'off' | 'silent' | 'loud'
export type FeedHookKind = 'stripe' | 'shopify' | 'github' | 'generic'
export type FeedHook = { id: string; name: string; kind: FeedHookKind; created: number; url: string; has_secret: boolean }
export type FeedSource = { source: string; label: string; builtin: boolean; rule: FeedRule; own_thread: boolean }
export type FeedSettings = { telegram: boolean; health: boolean; sources: FeedSource[]; hooks: FeedHook[]; kinds: FeedHookKind[]; rules: FeedRule[] }

/* ---------------------------------------------------------------- Import */
export type ImportAgent = 'hermes' | 'claude-code' | 'openclaw' | 'other'
export type ImportTopic = { name: string; source: string; files: number; exists: boolean }
export type ImportProject = { name: string; exists: boolean; topics: ImportTopic[] }
export type ImportPlan = {
  id: string
  name: string
  projects: ImportProject[]
  skills: string[]
  aside: string[]
  root_memory: boolean
  files: number
  size: number
  skipped: { file: string; reason: string }[]
  secrets: { file: string; kinds: string[] }[]
  renamed: { from: string; to: string }[]
}
export type ImportResult = {
  ok: boolean
  projects: string[]
  topics: string[]
  files: number
  merged: string[]
  renamed: { from: string; to: string }[]
  skills: string[]
  aside: string[]
  secrets: { file: string; kinds: string[] }[]
  folder: string
  report: string
  finish_prompt: string
}

/* ---------------------------------------------------------------- Trash */
export type TrashKind = 'file' | 'folder' | 'topic' | 'project' | 'session' | 'previous_versions'
export type TrashItem = { id: string; kind: TrashKind; name: string; original: string; at: number; size: number; sessions: number; restorable: boolean }
export type TrashList = { items: TrashItem[]; keep_days: number }
export type TrashRestoreResult = { ok: boolean; kind: TrashKind; restored_to: string; sessions: number }
export type InvalidatePayload = { topics: BusTopic[] }

/* ---------------------------------------------------------------- Files */
export type FileEntry = { name: string; path: string; type: 'file' | 'dir'; size: number; mtime: number; mime: string }
export type FileList = { path: string; parent: string | null; root: string; entries: FileEntry[] }
export type FileContent = { path: string; content: string; mtime: number; size: number; mime: string; editable: boolean }
export type FileWriteBody = { path: string; content: string; expected_mtime?: number }
export type FileWriteResult = { ok: boolean; mtime: number }
export type FileSearchHit = { path: string; name: string; type: 'file' | 'dir' }

/* ---------------------------------------------------------------- Tasks */
export type TaskStatus = 'todo' | 'doing' | 'done'
export type TaskPriority = 0 | 1 | 2 | 3
export type Task = {
  id: string
  title: string
  notes: string
  status: TaskStatus
  priority: TaskPriority
  due: string | null
  project_id: string | null
  topic_path: string | null
  labels: string[]
  created: number
  updated: number
  done_at: number | null
  order: number
}
/** `workspace` = the workspace project it follows (created, renamed with it); `hidden` = left out of the sidebar. */
export type TaskProject = { id: string; name: string; color: string; workspace?: string | null; hidden?: boolean }
export type TasksPayload = { projects: TaskProject[]; tasks: Task[] }
export type TaskInput = Partial<Omit<Task, 'id' | 'created' | 'updated'>> & { title?: string }
/** PATCH extras: the cards a task was dropped between (the server places it there, renumbering when needed). */
export type TaskPlace = { prev_id?: string; next_id?: string }
export type TaskProjectInput = { name: string; color: string; hidden?: boolean }
export type TaskBulkBody = {
  ids: string[]
  patch?: Partial<Pick<Task, 'status' | 'priority' | 'project_id' | 'due' | 'topic_path' | 'labels'>>
  labels_add?: string[]
  labels_remove?: string[]
  delete?: boolean
}
export type TaskBulkResult = { ok: boolean; updated: number; deleted: number }

/* ---------------------------------------------------------------- Crons */
export type CronKind = 'shell' | 'claude'
export type CronNotify = 'never' | 'failure' | 'always'
/** Who started a run: by hand, the schedule, a catch-up of a missed run, an automatic retry. */
export type CronTrigger = 'manual' | 'schedule' | 'catch-up' | 'retry'
export type CronLastRun = { at: number; ok: boolean; code: number; duration_s: number; trigger?: CronTrigger | ''; attempt?: number; silent?: boolean }
export type CronPermissionMode = '' | PermissionMode
export type Cron = {
  id: string
  name: string
  schedule: string
  kind: CronKind
  command: string
  topic_path: string
  prompt: string
  model: string
  reuse_session: boolean
  /** '' = the topic's mode, else the global one. */
  permission_mode?: CronPermissionMode
  enabled: boolean
  notify: CronNotify
  timeout_s: number
  /** One-time job: its date and time ("YYYY-MM-DDTHH:MM" in the configured zone); `schedule` is then "". */
  once_at?: string
  /** Unix time of `once_at` (null for a schedule). */
  once_ts?: number | null
  /** One-time job: removed once it ran (else disabled and marked done). */
  delete_after?: boolean
  /** One-time job that ran (or was missed for good): when. */
  done_at?: number | null
  missed?: boolean
  /** Make up for a run missed while the server was down (default true). */
  catch_up?: boolean
  /** Shell job: automatic retries after a failure (0-5). */
  retries?: number
  /** An automatic retry waits until then. */
  retry_at?: number | null
  last_run: CronLastRun | null
  next_run: number | null
  human: string
  /** A run is in progress (overlapping runs are skipped). */
  running: boolean
}
export type CronInput = Partial<Omit<Cron, 'id' | 'last_run' | 'next_run' | 'human' | 'once_ts' | 'done_at' | 'missed' | 'retry_at'>>
export type CronRun = {
  id: string
  cron_id: string
  name: string
  at: number
  ok: boolean
  code: number
  duration_s: number
  output_tail: string
  session_id: string | null
  trigger?: CronTrigger
  /** Attempt number (absent = 1). */
  attempt?: number
  /** Catch-up: the missed time it made up for. */
  slot?: number
  /** The answer was [SILENT]: nothing reported. */
  silent?: boolean
  /** It failed and will be tried again then. */
  retry_at?: number
}
export type ExternalCron = { schedule: string; command: string; human: string }
export type CronsPayload = { jobs: Cron[]; external: ExternalCron[] }
export type CronPreview = { valid: boolean; human: string; next: number[]; error?: string; once?: boolean }

/* ---------------------------------------------------------------- Telegram */
export type TelegramBot = { id: number; username: string; name: string }
export type TelegramChat = { id: number; title: string; type: string }
/** Special threads have a path ('#crons', '#alerts'); session threads a session_id. */
export type TelegramThread = { path: string; thread_id: number; name: string; session_id?: string }
/** simple = one chat (alerts + sessions as replies); threads = one thread per open session; mirror = threads + web turns copied. */
export type TelegramMode = 'simple' | 'threads' | 'mirror'
export type TelegramSettings = { mode: TelegramMode; notify_crons: boolean; notify_system: boolean; login_alerts: boolean; two_factor?: boolean; reply_mode: 'final' | 'progress'; thread_days: number; mirror_web: boolean }
export type PcBrowser = 'brave' | 'chrome' | 'edge' | 'vivaldi' | 'opera' | 'chromium'
export type PcOs = 'windows' | 'darwin' | 'linux'
export type PcStatus = {
  device: { id: string; name: string; os: string; arch: string; version: string; browsers: PcBrowser[]; browser: PcBrowser; created: number; last_seen: number } | null
  online: boolean
  browser_running: boolean
  mcp_running: boolean
  last_use: number | null
  pairing: { expires_at: number; browser: PcBrowser; os: PcOs } | null
  /** a PC that used a download code and waits for the user's yes */
  candidate: { id: string; name: string; os: string; arch: string; version: string; created: number; ip?: string } | null
  /** a Harness PC can be downloaded from this server (a release is listed, or a local build) */
  available: boolean
  mcp_registered: boolean
  settings: { idle_min: number }
  browsers: PcBrowser[]
  targets: string[]
  actions: { at: number; tool: string; args: Record<string, string>; ok: boolean; ms: number }[]
}
export type PcPairing = { code: string; expires_at: number; expires_in: number; server: string; downloads: Record<string, string>; commands: Record<PcOs, string> }

export type TelegramStatus = {
  configured: boolean
  running: boolean
  bot: TelegramBot | null
  chat: TelegramChat | null
  topics_enabled: boolean
  mode: TelegramMode
  threads: TelegramThread[]
  /** Agents with the Telegram option: their own thread, in every mode. */
  agent_threads?: { path: string; thread_id: number; name: string }[]
  settings: TelegramSettings
  /** A link code is pending (/start <code>). */
  linking: boolean
  /** The last link code (pending or expired), kept by the server: the page can be left and opened again. */
  link?: TelegramLink | null
  /** Error of the poller (getUpdates), cleared by its next success. `token_rejected` = 401, the poller stopped. */
  poll_error?: string | null
  poll_error_code?: 'token_rejected' | 'conflict' | 'unreachable' | null
  /** Error of the last thread sync. */
  sync_error?: string | null
  /** Threads are off for this bot (BotFather "Threaded Mode"): everything goes to the main chat. Not an error. */
  topics_notice?: string | null
  /** Last successful getUpdates (Unix seconds) and its age in seconds. */
  last_poll_ok?: number | null
  last_poll_age?: number | null
  /** Older field: poll_error or sync_error. */
  last_error: string | null
}
export type TelegramLink = { code: string; deep_link: string; expires_at: number; expires_in: number; expired: boolean }
export type TelegramTokenResult = { ok: boolean; bot?: TelegramBot; error?: string }
export type TelegramLinkStart = { code: string; deep_link: string; expires_at: number; expires_in: number }
export type TelegramLinkState = { linked: boolean; chat: TelegramChat | null; pending?: TelegramLink | null }
export type TelegramSyncResult = { created: number; deleted?: number; topics_enabled: boolean; error: string | null; notice?: string | null }
export type TelegramTestResult = {
  ok: boolean
  sent: boolean
  poller: { running: boolean; last_poll_ok: number | null; last_poll_age: number | null; error: string | null; error_code: string | null }
  webhook: { url: string; pending_updates: number; last_error: string | null } | null
  problems: string[]
}

/* ---------------------------------------------------------------- Backup */
export type BackupRun = { at: number; ok: boolean; commit: string | null; files: number; changed?: number; error: string | null; code?: string; duration_s?: number }
export type BackupStatus = {
  configured: boolean
  repo: string | null
  private: boolean | null
  schedule: string
  include: string[]
  /** CLAUDE.md / memory.md globs, always included. */
  always: string[]
  last: BackupRun | null
}
export type BackupConfigBody = { repo: string; token: string; create?: boolean }
export type BackupConfigResult = { ok: boolean; private: boolean; created?: boolean; warning?: string; error?: string }
export type BackupSettingsBody = { schedule?: string; include?: string[] }
export type BackupRunResult = {
  ok: boolean
  commit: string | null
  files: number
  changed?: number
  error?: string
  code?: string
  leaks?: { file: string; kinds: string[] }[]
}
export type BackupRestoreResult = { ok: boolean; files: number; restored: string[]; unchanged: number; crons: boolean; trash: string }

/* ---------------------------------------------------------------- Profile (pseudo) */
export type ProfileColor = 'clay' | 'blue' | 'violet' | 'green' | 'amber' | 'rose' | 'teal' | 'zinc'
export type Profile = { name: string; color: ProfileColor | ''; emoji: string }
/** Saying hello to the authors (all optional): anonymous counter, email (+ product news). */
export type LicenseState = { has_key: boolean; key_hint: string; kind?: string | null; email?: string | null; max_servers?: number | null; expires_at?: number | null; activated_at?: number | null; enabled: boolean; moved_to_git?: number | null }
export type RegisterState = { count: boolean; /** MAXXING_NO_TELEMETRY / DO_NOT_TRACK set on the server: counter off whatever `count`. */ count_blocked: boolean; email: string; news: boolean; asked: boolean; registered: boolean; error: string; synced_at: number }

/* ---------------------------------------------------------------- Settings & secrets */
export type Settings = {
  timezone: string
  language: Language
  public_url: string
  files_root: string
  presentation_default?: boolean
  usage_widget: boolean
  /** Settings -> Features: the Tasks page (/tasks), its sidebar entry and dashboard widget (off when new) */
  tasks_page?: boolean
  /** Settings -> Features: the Git & GitHub page (/git) and its sidebar entry */
  git_page: boolean
  /** Settings -> Features: the Infra page (/infra) and its sidebar entry */
  infra_page: boolean
  /** Settings -> Features: the Team page (/team, chats between people) and its sidebar entry */
  team_page?: boolean
  /** Settings -> Features: the Agents page (/agents, lasting roles of a topic with triggers) and the agent rows of the tree */
  agents_page?: boolean
  /** Settings -> Features (beta): Maxxing mode on the Sessions page (its switch, meter and Alt+M) */
  maxxing_mode?: boolean
  /** Settings -> Features: the E-mail page (/mail) and its sidebar entry */
  mail_page?: boolean
  /** memory-compaction line limit per memory.md (0 = none). */
  memory_max_lines: number
  /** Parts of the line under each answer that are hidden (every browser of the installation). */
  result_line_hidden?: ResultField[]
  /** Settings -> Support: hide the donation links of What's new, Feedback and License (every browser). */
  donation_hidden?: boolean
}
export type ResultField = 'model' | 'duration' | 'cost' | 'tokens' | 'cache'

/* ---------------------------------------------------------------- Memory, stats, changelog */
export type MemoryFile = { path: string; level: 'global' | 'project' | 'topic'; lines: number; bytes: number; over: boolean }
export type MemoryInfo = { max_lines: number; files: MemoryFile[] }
export type TokenCounts = { input: number; output: number; cache_read: number; cache_write: number; total: number; cost_usd: number; turns: number; sessions: number }
export type TokenStats = {
  totals: TokenCounts
  projects: (TokenCounts & { name: string })[]
  topics: (TokenCounts & { path: string })[]
  sessions: (Omit<TokenCounts, 'sessions'> & { id: string; title: string; path: string; archived: boolean; updated: number })[]
  days: { date: string; tokens: number; cost_usd: number }[]
  /** Recent turns: median seconds until Claude Code's first event (start) and its first answer. */
  latency?: { start_s: number | null; first_answer_s: number | null; turns: number }
  at: number
}
export type ChangelogEntry = { version: string; label: string; current: boolean; body: string }
export type Changelog = { version: string; entries: ChangelogEntry[] }
export type Secret = { name: string; note: string; expose: boolean; updated: number; preview: string }
/** A file of the Keys vault: only its description, the content never reaches the browser. */
export type SecretFile = { name: string; filename: string; size: number; sha256: string; note: string; expose: boolean; updated: number }
export type SecretFilePutBody = { file?: File; note?: string; expose?: boolean; create?: boolean }
export type SecretPutBody = { value?: string; note?: string; expose?: boolean; create?: boolean }

/* ---------------------------------------------------------------- System */
/** `seen`: marked as seen - it does not count in the sidebar until it changes or for 24 h. */
export type HealthIssue = { level: 'info' | 'warn' | 'error'; code: string; text: string; id?: string; seen?: boolean }
export type Health = {
  ok: boolean
  issues: HealthIssue[]
  cpu_pct: number
  load: number[]
  mem: { total: number; avail: number }
  disk: { total: number; free: number; pct: number }
  uptime_s: number
  claude_auth: boolean
  claude_auth_error?: string | null
  claude_checked_at?: number | null
  backup_age_h: number | null
  failed_logins_1h: number
  at: number
}
export type Service = { name: string; label: string; active: boolean; enabled: boolean; since: number | null; state: string }
export type ServiceAction = 'start' | 'stop' | 'restart'
export type LogsPayload = { lines: string[] }
export type VersionInfo = {
  version: string
  commit: string
  latest_commit: string | null
  behind: number | null
  checking?: boolean
  checked_at?: number | null
  /** Changes made to the product code on this server (kept as local commits, carried over by updates). */
  custom?: { count: number; titles: string[]; dirty: number; rebase: boolean }
  /** Last update stopped: customizations conflict, or the new version did not start (rolled back). */
  pending?: { at: number; reason: 'conflict' | 'health' | 'dependencies' | string; target_version?: string; conflicts?: string[] } | null
  /** License of this server (licensed installs get their updates from the license server). */
  license?: { enabled: boolean; key_hint: string; email?: string | null; kind?: string | null; updates_until?: number | null; expires_at?: number | null; channel?: string | null; latest?: string | null; message?: string | null; max_servers?: number | null; moved_to_git?: number | null; move_error?: string | null }
  /** Last verification (after an update, or on demand): extensions load, customization checks pass. */
  report?: { at: number; version: string; ok: boolean; problems: number } | null
  /** Last update seen by the restarted server; notes_session = the Harness session applying its upgrade notes. */
  after?: { to: string; at: number; notes_session?: string | null; notes_path?: string | null; done?: boolean } | null
  /** Automatic update while nobody is on the interface (`auto_update`, default off). */
  auto_update?: { enabled: boolean; tried?: { target: string; version?: string; at: number } | null; last_check?: { at: number; verdict: string } | null }
}
export type PreflightCustom = {
  id: string
  title: string
  why: string
  files: string[]
  /** ok = carries over · review = carries over on code that changed · included = now in the product · conflict */
  status: 'ok' | 'review' | 'included' | 'conflict' | 'unknown'
  conflicts: string[]
  overlap: string[]
}
/** GET /api/system/update/preflight: the next update simulated on a throw-away copy of the code. */
export type Preflight = {
  ok: boolean
  verdict: 'up_to_date' | 'simple' | 'adapt' | 'unavailable'
  current: string
  latest: string
  behind: number
  customs: PreflightCustom[]
  unsaved: string[]
  unsaved_overlap?: string[]
  web_changes: string[]
  extensions: { id: string; name: string; api: number; reason: string }[]
  notes: { version: string }[]
}
export type UpdateReport = {
  at: number
  version: string
  ok: boolean
  problems: number
  extensions: { id: string; name: string; type: string; ok: boolean; error: string; skipped?: boolean }[]
  checks: { id: string; title: string; check: string; ok: boolean; output: string }[]
}
export type UsageWindow = { pct: number | null; resets_at: number | null }
export type UsagePayload = {
  available: boolean
  five_hour: UsageWindow | null
  seven_day: UsageWindow | null
  /** "Pro", "Max", "Ultra"... (Max 20x is "Ultra" since 2026-10-31); null when the sign-in does not tell. A verified
   *  Ultra account has no 5-hour window: five_hour is then null. */
  plan?: string | null
  /** disabled | no_oauth_credentials | api_key | rate_limited | http_<status> | <exception name> */
  reason?: string
  /** "turn": read in the last turn's rate_limit_event (no call), at `seen_at` (Unix seconds). */
  source?: 'turn'
  seen_at?: number
  stale?: string | boolean
  /** Rate limited: no new reading before this time (Unix seconds). */
  retry_at?: number
}

/* ---------------------------------------------------------------- Docs */
export type DocMeta = { slug: string; title: string; section: string; order: number }
export type DocPage = { slug: string; title: string; markdown: string }

/* ---------------------------------------------------------------- Dashboard & extensions */
export type StatBlock = { type: 'stat'; label: string; value: string | number; hint?: string; delta?: string | number; tone?: Tone }
export type Block =
  | StatBlock
  | { type: 'stats'; items: Omit<StatBlock, 'type'>[] }
  | {
      type: 'list'
      items: { title: string; subtitle?: string; value?: string | number; href?: string; status?: Tone; /** lucide name (NamedIcon), preferred */ icon?: string; emoji?: string }[]
      empty?: string
      /** tiles side by side (2-3 per row) instead of rows: shortcuts, examples */
      grid?: boolean
    }
  | { type: 'chart'; kind: 'bar' | 'line'; series: { name: string; points: [number | string, number][] }[]; unit?: string }
  | { type: 'table'; columns: string[]; rows: (string | number | null)[][] }
  /** format "percent" shows value/max as "4.5 %"; otherwise "value / max unit" ("2.3 / 16.4 GB"). */
  | { type: 'progress'; label: string; value: number; max: number; hint?: string; unit?: string; format?: 'percent' | 'fraction' }
  | { type: 'markdown'; text: string }
  | TimelineBlock
/** Events on a time axis, one lane per row (Unix seconds). `dense` lanes draw a band instead of dots. */
export type TimelineEvent = { at: number; state?: 'ok' | 'error' | 'running' | 'planned'; label?: string }
export type TimelineBlock = {
  type: 'timeline'
  start: number
  end: number
  now?: number
  lanes: { name: string; sub?: string; color?: string; dense?: boolean; href?: string; events: TimelineEvent[] }[]
  more?: string | null
}
export type Card = {
  title?: string
  status?: Tone
  link?: string
  blocks: Block[]
  updated?: number
  /** HTML widget: URL of its widget.html (drawn in a sandboxed frame) and its height in px. */
  html?: string
  height?: number
}
export type Widget = {
  id: string
  title: string
  icon: string
  span: 1 | 2 | 3
  source: 'builtin' | 'extension'
  card: Card | null
  error: string | null
  /** Hidden by the layout (card is null). Listed so the edit mode can show it again. */
  hidden?: boolean
  /** Still computing when the dashboard answered: fetch it alone (GET /api/dashboard/widgets/{id}). */
  pending?: boolean
  /** With pending: `card` is the last one computed (past its TTL), shown until the new one arrives. */
  stale?: boolean
}
export type DashboardPayload = { widgets: Widget[] }
export type DashboardLayout = { order: string[]; hidden: string[] }

export type Extension = {
  id: string
  name: string
  /** view = an extension that only brings views (agents_view) */
  type: 'widget' | 'page' | 'view'
  icon: string
  version: string
  enabled: boolean
  error: string | null
  has_api: boolean
  /** An Office view of the Agents page (manifest "agents_view" + agents-view.html), in the UI language; null without. */
  agents_view?: { name: string; icon: string } | null
  /** Page extensions: own entry in the sidebar (otherwise listed under "Extensions"). */
  pinned?: boolean
  /** page.js mtime (ms): version of the module URL (the browser reuses it until the file changes). */
  page_v?: number | null
}

/** A starter pack (GET /api/packs). */
export type Pack = {
  id: string
  project: string
  /** given to the project when it has none */
  emoji: string
  /** lucide name shown for the pack (NamedIcon) */
  icon: string
  title: string
  description: string
  topics: string[]
  crons: string[]
  installed: boolean
  partial: boolean
  project_exists: boolean
  /** the default projects (general, system): installing puts back what was deleted */
  basics: boolean
}
/** `project` = the project created ("ecommerce-2" when "ecommerce" exists), "" for the basics */
export type PackInstallResult = { ok: true; pack: Pack; project: string; created_files: number; jobs: string[] }

/* ---------------------------------------------------------------- Git (GET /api/git/*) */
export type GitRef = { name: string; kind: 'head' | 'branch' | 'remote' | 'tag'; current?: boolean }
export type GitCommit = { sha: string; parents: string[]; refs: GitRef[]; author: string; date: number; subject: string }
/** A clone on the server (local_repos) or the summary of a graph's repository. */
export type GitLocalRepo = {
  path: string
  name: string
  branch: string | null
  upstream: string | null
  ahead: number
  behind: number
  changed: number
  untracked: number
  last_commit: number | null
  last_subject: string
  remote: string | null
  /** "owner/name" when origin is on GitHub */
  github: string | null
  error: string | null
  /** other worktree folders of this clone (one per branch), not listed on their own */
  worktrees?: number
}
export type GitPermission = 'admin' | 'maintain' | 'push' | 'triage' | 'pull' | 'none'
export type GitHubRepo = {
  full_name: string
  owner: string
  name: string
  description: string
  private: boolean
  fork: boolean
  archived: boolean
  permission: GitPermission
  default_branch: string | null
  pushed_at: string | null
  url: string
  language: string | null
  stars: number
  open_issues: number
  /** clones of it on this server */
  local_paths: string[]
  /** vault keys that see it (names only) and the accounts behind them */
  keys: string[]
  accounts: string[]
}
export type GitHubAccount = { login: string; name: string | null; avatar: string | null; keys: string[]; repos: number }
export type GitOverview = {
  root: string
  local: GitLocalRepo[]
  /** every account behind the server's GitHub tokens (any vault key holding one), merged */
  github: { connected: boolean; login: string | null; accounts: GitHubAccount[]; errors: { key: string; error: string }[]; error: string | null; repos: GitHubRepo[] }
}
export type GitGraphRepo = Partial<GitLocalRepo> & {
  kind: 'local' | 'github'
  /** what to pass back as `repo`: a path or github:owner/name */
  id: string
  name: string
  branch: string | null
  github: string | null
  url?: string
  private?: boolean
  permission?: GitPermission
  description?: string
  branches?: number
  branches_shown?: number
}
export type GitGraph = { repo: GitGraphRepo; commits: GitCommit[]; truncated: boolean }
export type GitCommitDetail = {
  sha: string
  parents: string[]
  author: string
  email: string
  date: number
  message: string
  files: { path: string; additions: number | null; deletions: number | null }[]
  files_total: number
  url?: string
}
export type GitPull = { number: number; title: string; author: string | null; head: string | null; base: string | null; draft: boolean; url: string; updated: number }

/* ---------------------------------------------------------------- Infra (server/maxxing/infra) */
export type InfraKind = 'server' | 'site' | 'worker' | 'pages' | 'database' | 'bucket' | 'domain'
export type InfraStatus = 'ok' | 'warn' | 'down' | 'unknown'
export type InfraRepo = { path?: string; github: string | null; branch?: string | null; git: string | null }
export type InfraCheck = { url: string; status: InfraStatus; code?: number; ms?: number; detail?: string; location?: string }
export type InfraResource = {
  id: string
  kind: InfraKind
  name: string
  /** "local" (this server), a registered server name, "cloudflare", "hostinger", a platform (vercel, netlify, supabase, github), "other" */
  location: string
  provider: string
  urls: string[]
  status: InfraStatus
  status_detail: string
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  details: Record<string, any>
  links: string[]
  project: string | null
  note: string
  hidden: boolean
  declared: boolean
  missing: boolean
}
export type InfraSource = {
  connected: boolean
  key: string | null
  error?: string | null
  sections?: Record<string, string | null>
  /** hosting platforms (server/maxxing/infra/platforms.py) */
  label?: string
  beta?: boolean
  token_url?: string
  keys?: string[]
}
export type InfraView = {
  enabled: boolean
  refreshing: boolean
  error: string | null
  generated_at: number | null
  took_ms: number | null
  harness_host: string | null
  sources: { servers?: Record<string, { ok: boolean; error: string | null; took_ms: number | null }>; cloudflare?: InfraSource; hostinger?: InfraSource } & Partial<
    Record<'vercel' | 'netlify' | 'supabase' | 'github', InfraSource>
  >
  resources: InfraResource[]
  servers: { name: string; label?: string; host: string; user: string; port: number; note: string }[]
  refresh_min?: number
}

// ---- E-mail page (server/maxxing/mail, docs/dev/API.md#mail)
export type MailTls = 'ssl' | 'starttls' | 'none'
export type MailAccount = {
  id: string
  label: string
  address: string
  name: string
  username: string
  imap_host: string
  imap_port: number
  imap_tls: MailTls
  smtp_host: string
  smtp_port: number
  smtp_tls: MailTls
  signature: string
  password_key: string
  has_password: boolean
  created?: number
  smtp_checked?: number
  /** recipients sent to today, and the daily cap (`mail_send_per_day`) */
  sent_today?: number
  send_per_day?: number
  /** minutes between two checks for new mail (5, 10, 30 or 60) */
  poll_min?: MailPollMin
  last_check?: MailCheck | null
  /** the agents that may use this mailbox (their grant) */
  agents?: MailAgentGrant[]
  /** messages written by agents waiting for the owner's OK */
  waiting?: number
  /** servers whose Authentication-Results are trusted (empty = automatic) */
  auth_servers?: string[]
  /** who checks the senders: the owner's servers, a known provider, one found but not confirmed, nobody */
  sender_check?: MailSenderCheck
}
export type MailSenderCheck = { state: 'owner' | 'auto' | 'detected' | 'none'; server: string }
export type MailPollMin = 5 | 10 | 30 | 60
export type MailCheck = { at: number; ok: boolean; error: string }
export type MailRight = 'read' | 'draft' | 'move' | 'mark' | 'send'
export type MailApproveSend = 'always' | 'new' | 'never'
export type MailTrigger = { enabled: boolean; folder: string; subject: string; senders: string[]; prompt: string }
/** An agent's access to one mailbox (agent.json `mail`): nothing by default. `senders` empty = all mail; else only
 *  mail whose sender the provider checked, and the agent writes only to them. */
export type MailGrant = { account: string; rights: MailRight[]; senders: string[]; approve_send: MailApproveSend; trigger: MailTrigger | null }
/** A grant as sent (POST / PATCH /api/agents): the server fills the trigger's missing fields. */
export type MailGrantInput = Omit<MailGrant, 'trigger'> & { trigger: Partial<MailTrigger> | null }
export type MailAgentGrant = Omit<MailGrant, 'account'> & { agent: string; name: string; avatar: AgentAvatar | null; enabled: boolean }
/** What an agent did with a message (mail.db, never written to the mailbox), oldest first. */
export type MailSeenBy = { agent: string; at: number; what: string; detail: string; name: string; avatar: AgentAvatar | null; exists: boolean }
export type MailRefreshResult = { account: string; ok: boolean; error?: string; new: number; started: number }
/** GET /api/mail/all: the newest mails of every mailbox, as the last checks saw them. */
export type MailAllRow = {
  account: string
  address: string
  folder: string
  uid: number
  message_id: string
  from: MailAddress
  from_verified: boolean
  subject: string
  date: number | null
  snippet: string
  seen: boolean
  attachments: boolean
  seen_by: MailSeenBy[]
}
export type MailAll = { messages: MailAllRow[]; checks: Record<string, MailCheck | null> }
/** A message written by an agent, waiting for the owner's OK (GET /api/mail/outbox). */
export type MailOutboxItem = {
  id: string
  account: string
  agent: string
  agent_name: string
  avatar: AgentAvatar | null
  at: number
  to: string[]
  cc: string[]
  subject: string
  text: string
  /** longer than what the page gets: never sent from the outbox (open the draft) */
  text_cut?: boolean
  files: { name: string; type: string; size: number }[]
  draft: { folder: string; uid: number } | null
  why: string
  event_id: string | null
  note: string
}
export type MailServerSettings = Pick<MailAccount, 'imap_host' | 'imap_port' | 'imap_tls' | 'smtp_host' | 'smtp_port' | 'smtp_tls'>
export type MailDetect = MailServerSettings & { source: 'known' | 'mx' | 'autoconfig' | 'guess'; mx: string[] }
export type MailTest = { imap: 'ok' | 'skipped'; smtp: 'ok' | 'error' | 'skipped'; smtp_port?: number; smtp_tls?: MailTls; smtp_changed?: boolean; smtp_error?: string; smtp_code?: string }
export type MailRole = 'inbox' | 'drafts' | 'sent' | 'archive' | 'junk' | 'trash' | 'all' | 'flagged'
export type MailFolder = { name: string; role: MailRole | null; delim: string | null; unread: number | null; total: number | null }
export type MailAddress = { name: string; email: string }
export type MailSummary = {
  uid: number
  from: MailAddress
  to: MailAddress[]
  subject: string
  date: number | null
  seen: boolean
  flagged: boolean
  answered: boolean
  size: number | null
  attachments: boolean
  message_id?: string
  /** the provider checked the sender's domain (DKIM / SPF / DMARC) */
  from_verified?: boolean
  seen_by?: MailSeenBy[]
}
export type MailList = { folder: string; total: number; exists: number; page: number; size: number; messages: MailSummary[] }
export type MailAttachment = { index: number; filename: string; content_type: string; size: number }
export type MailMessage = {
  uid: number
  folder: string
  from: MailAddress
  to: MailAddress[]
  cc: MailAddress[]
  reply_to: MailAddress[]
  bcc?: MailAddress[]
  subject: string
  date: number | null
  message_id: string
  in_reply_to?: string
  references: string
  text: string | null
  html: string | null
  remote_images: boolean
  attachments: MailAttachment[]
  /** Parts past the server's limit: not listed, not downloadable. */
  attachments_more?: number
  seen: boolean
  flagged: boolean
  answered: boolean
  from_verified?: boolean
  seen_by?: MailSeenBy[]
}
export type MailComposeMode = 'reply' | 'replyall' | 'forward' | 'draft'
/** Prefilled fields of a reply / forward / draft opened again (GET /api/mail/{acc}/compose). */
export type MailCompose = {
  to: string[]
  cc: string[]
  bcc?: string[]
  subject: string
  text: string
  in_reply_to: string
  references: string
  attachments: MailAttachment[]
}
/** The JSON part of POST /api/mail/{acc}/send and /draft. */
export type MailDraft = {
  to: string[]
  cc: string[]
  bcc: string[]
  subject: string
  text: string
  in_reply_to?: string
  references?: string
  reply?: { folder: string; uid: number }
  forward?: { folder: string; uid: number; indexes: number[] }
  draft?: { folder: string; uid: number }
}
export type MailSent = { ok: boolean; message_id: string; recipients: number; refused: string[]; sent_folder: string | null }
export type MailAction = 'seen' | 'unseen' | 'flag' | 'unflag' | 'move' | 'archive' | 'trash' | 'junk' | 'inbox' | 'delete'
