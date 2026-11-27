// TypeScript mirror of docs/dev/API.md. Keep in sync with the contract (change API.md first).
// Timestamps are Unix seconds (float).
import type { Look } from '@/stores/ui'

export type Ok = { ok: boolean }
export type Language = 'en' | 'fr'
export type Tone = 'ok' | 'warn' | 'error'

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
export type TwoFactorChallenge = { challenge: string; expires_in: number; methods?: ('telegram' | 'totp')[] }
export type SecondFactor = { telegram: boolean; totp: boolean; recovery_left: number }
export type TotpEnrol = { secret: string; uri: string }
export type RecoveryCodes = { recovery_codes: string[] }
export type SignedInBrowser = { id: string; label: string; ip: string; created: number; seen: number; current: boolean }
export type SignedInBrowsers = { devices: SignedInBrowser[]; legacy: boolean; legacy_current: boolean }
export type LoginResult = { ok: boolean; two_factor?: TwoFactorChallenge }
export type TwoFactorPoll = { ok: boolean; status: 'pending' | 'approved'; expires_in?: number }
export type ChangePasswordBody = { current: string; new: string }

/* ---------------------------------------------------------------- Onboarding */
type OnboardingStepKey = 'password' | 'claude' | 'workspace' | 'telegram' | 'backup' | 'profile'
export type OnboardingState = { completed: boolean; steps: Record<OnboardingStepKey, boolean> }

/* ---------------------------------------------------------------- Claude */
export type ClaudeAuthMethod = 'oauth_token' | 'credentials' | 'api_key' | null
/** `ask`: what is not pre-allowed waits for the user's Allow / Deny (topics, global setting, jobs; not agents). */
export type PermissionMode = 'bypass' | 'sandbox' | 'acceptEdits' | 'default' | 'ask'
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
type ClaudeAutoUpdate = {
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
  /** Unread sessions whose last turn failed (among `unread`): the counter turns red. */
  errors?: number
  telegram_thread: number | null
  /** The topic's "Always allow" rules (Claude Code rules added from an approval card). */
  allowed_tools?: string[]
  /** Sessions in the order chosen by drag and drop (ids); the others (new ones) come first, by activity. */
  session_order?: string[]
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
type AgentAvatarOptions = Record<keyof AgentAvatar, string[]>
export type AgentLimits = { usd_per_day: number; runs_per_hour: number; timeout_s: number; debounce_s: number; /** `chat`: hours of silence after which a new conversation starts (0 = never) */ chat_idle_h?: number }
/** kind feed: events of a feed source; kind agent: the end of an automatic run of another agent (`agent` = its path). */
export type AgentTrigger = { id: string; kind: 'feed' | 'agent'; enabled: boolean; source: string; levels: FeedLevel[]; match: string; prompt: string; hook_id?: string; agent?: string; on?: AgentChainOn }
export type AgentChainOn = 'ok' | 'error' | 'any'
export type AgentTriggerInput = Partial<AgentTrigger>
type AgentThreadKind = 'note' | 'run' | 'result' | 'skip' | 'approval'
export type AgentMessage = { id: string; at: number; kind: AgentThreadKind; text: string; trigger?: string; source?: string; session?: string; ok?: boolean; cost?: number; reason?: string; /** run: the thread message it answers (its session went on) */ reply_to?: string; /** approval / its note: the request id */ approval?: string; /** note of an approval: allow, deny, timeout, expired */ status?: string; /** run: the files sent with it (absolute paths) */ attachments?: string[]; /** run: typed by the owner (page, Telegram) */ owner?: boolean; /** run: it started a new conversation */ chat?: 'new'; /** result: the tools its turn used (the last 40), how many in all, its model and duration */ tools?: AgentStep[]; tools_total?: number; model?: string; duration_ms?: number; /** note of a change: the files changed */ files?: string[]; /** its text was cut: its whole length */ cut?: number; /** run of the owner: waits for the run that holds the budget */ waiting?: boolean; /** run of the owner: a voice message sent directly (its recording; `text` = its transcript once heard) */ voice?: string[]; /** its voice message could not be transcribed */ voice_error?: string }
/** A tool a turn of an agent used, as kept in its thread. */
type AgentStep = { name: string; summary: string; error?: boolean }
export type AgentRuleTool = 'Bash' | 'Write' | 'Edit' | 'WebFetch' | '*'
/** "Refuse <tool> when it contains <match>", `reason` shown to Claude. */
export type AgentRule = { tool: AgentRuleTool; match: string; reason: string }
/** GET /api/agents/sandbox: what the sandbox needs on this server (missing among bwrap, socat, apparmor, linux). */
export type AgentSandboxStatus = { ok: boolean; missing: string[] }
/** POST /api/agents/import: the agent made from a Claude Code agent file; `ignored` = its fields with no equivalent. */
export type AgentImportResult = Agent & { ignored: string[] }
/** An agent = a folder projects/<p>/topics/<t>/agents/<name>/ (CLAUDE.md = its role, memory.md, agent.json). */
export type Agent = {
  /** answer of a save only: its first outside source (webhook, feed, mailbox) turned its sandbox on */
  sandbox_auto?: boolean
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
  /** works without notifying the user (no Telegram, alerts already read, nothing unread) */
  silent: boolean
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
  /** the model of the owner's conversation ('' = `model`) */
  chat_model?: string
  limits: AgentLimits
  triggers: AgentTrigger[]
  /** mailboxes of the E-mail page it may use (none by default) */
  mail?: MailGrant[]
  /** May it use the Harness Browser (maxxing/browser): off unless turned on. */
  browser?: BrowserSwitch
  /** The person's devices it may use (ids; none unless turned on). */
  devices?: string[]
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
  /** the conversation the owner's next message goes on in (`chat`), null = a new one */
  chat_session?: string | null
  /** the owner's last conversation (to read it again once a new one is due) */
  last_chat_session?: string | null
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
  /** the message an idea of a new agent's conversation puts in the box (My job / When / Results / Never without me) */
  brief: string
  /** shown first among the ideas (the others behind "More ideas") */
  first: boolean
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
type AgentHook = { id: string; name: string; kind: AgentWebhookKind; url: string; has_secret: boolean }
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
  silent?: boolean
  approvals?: boolean
  trust_outside?: boolean
  keys?: string[]
  sandbox?: boolean
  domains?: string[]
  writable?: string[]
  rules?: AgentRule[]
  subagent?: boolean
  chat_model?: string
  limits?: Partial<AgentLimits>
  triggers?: AgentTriggerInput[]
  mail?: MailGrantInput[]
  browser?: BrowserSwitch
  devices?: string[]
}
export type AgentRunResult = { started: boolean; /** the new session (its id in older answers) */ session?: Session | string; reason?: string; /** a reply: the session of that message went on */ continued?: boolean }
export type AgentWebhookKind = 'generic' | 'stripe' | 'shopify' | 'github'
export type AgentWebhookResult = { agent: AgentDetail; hook: { id: string; name: string; kind: AgentWebhookKind; url: string; has_secret: boolean } }
export type NameBody = { name: string; description?: string }
export type PatchNameBody = { name?: string; description?: string; /** Projects only; "" removes it. */ emoji?: string; /** Topics only; "" = the global setting. */ permission_mode?: '' | PermissionMode; /** Topics only: the whole list of "Always allow" rules. */ allowed_tools?: string[] }

/* ---------------------------------------------------------------- Sessions */
type SessionState = 'idle' | 'running' | 'error'
type SessionSource = 'web' | 'telegram' | 'cron' | 'agent' | 'session' | 'cli' | 'github' | 'system' | 'browser'
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
  /** `claude --effort` of the next turns: low | medium | high | xhigh | max, "" = Claude Code's default. */
  effort?: Effort | ''
  real_model: string | null
  context_tokens: number | null
  /** Context window of the last turn's model (e.g. 1 000 000); null when unknown. */
  context_window: number | null
  archived: boolean
  /** Pinned in the Favorites block of the sessions list (stored on the server: same on every device). */
  favorite: boolean
  notify: boolean
  /** Mobile notifications of this session (false = muted on the phones). */
  push?: boolean
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
  /** Git repositories its turns changed (Changes view, terminal tabs). */
  code_repos?: string[]
  /** Its separate copy (Code mode): its own folder and branch of the topic's repository. */
  worktree?: SessionCopy | null
  /** `ask_human` requests of its browser waiting for the user (GET /api/browser/asks?session=). */
  browser_asks?: number
  /** its browser's exit went down during a turn (the card "go on when it is back") */
  browser_exit?: BrowserWaiter | null
  /** `ask_human` requests on the person's devices waiting for them (GET /api/devices/session/<id>). */
  device_asks?: number
  /** Its own compaction threshold (Jarvis's conversation), else null: the server's auto_compact_tokens. */
  compact_tokens?: number | null
}
/** A session's separate copy (server: maxxing/worktrees.py). */
type SessionCopy = {
  path: string
  repo: string
  branch: string
  base: string
  pr?: { number: number; url?: string; fork?: boolean; full?: string } | null
  kept_branch?: string | null
  removed: boolean
  preparing: boolean
}
/** A tool call an agent waits on (agents with `approvals`): Allow / Deny in the session. */
export type Approval = {
  id: string
  session: string
  agent_path: string
  tool: string
  /** agent_change: an agent's conversation asks to change its safety settings (input.description = the change) */
  kind?: string
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
  /** The rule "Always allow" would add to the session's topic ("" = not offered: agents, multi-line commands...). */
  always_rule?: string
  /** the session runs in its topic's sandbox: the request offers "Full access for this topic" */
  full_access?: boolean
}
export const EFFORTS = ['low', 'medium', 'high', 'xhigh', 'max'] as const
export type Effort = (typeof EFFORTS)[number]
export type CreateSessionBody = { path: string; message?: string; title?: string; model?: string; effort?: Effort | ''; attachments?: string[]; plan_mode?: boolean; /** false: never rings the phones. */ push?: boolean; /** Absolute path of a voice message sent directly. */ voice?: string; /** This page's id for the first message (see SendMessageBody). */ client_id?: string; /** Work on a separate copy (Code mode). */ worktree?: { repo: string; base?: string; prepare?: string; copy_env?: boolean; remember?: boolean } }
export type PatchSessionBody = { title?: string; model?: string; effort?: Effort | ''; archived?: boolean; notify?: boolean; push?: boolean; plan_mode?: boolean; favorite?: boolean; /** Move to another topic (idle sessions only). */ path?: string }
export type SendMessageBody = { text: string; attachments?: string[]; /** Sent during a voice call, in that language: Claude answers short and easy to say. */ call?: string; /** Absolute path of a voice message sent directly: the server transcribes it, then sends it. */ voice?: string; /** This page's id for the message, found again in `client_ids` of its queue item and its log event (a reload mid-send checks it). */ client_id?: string; /** The @ of the composer: the server tells Claude how to write to each. */ mentions?: Mention[] }
export type SendMessageResult = { queued: boolean; session: Session }
/** Who the composer's @ can name (GET /api/sessions/{id}/mentions). */
type MentionKind = 'jarvis' | 'session' | 'agent' | 'team'
type Mention = { kind: MentionKind; ref: string }
/** A name of a sent message (log line `mentions`). */
export type SentMention = Mention & { label: string; group?: boolean; avatar?: Partial<AgentAvatar> | null }
export type MentionTarget = Mention & { label: string; hint: string; state?: string; avatar?: Partial<AgentAvatar> | null; group?: boolean }
type SearchKind = 'session' | 'file' | 'memory' | 'task' | 'group'
/** Full-text hit: `snippet` marks the matched words with \u0002 … \u0003. */
export type SearchHit = { kind: SearchKind; id: string; path: string; title: string; snippet: string; at: number | null; score: number }
export type SearchResult = { results: SearchHit[]; took_ms: number }
type Upload = { path: string; name: string; size: number; mime: string }
export type UploadResult = { files: Upload[] }

type Usage = { input: number; output: number; cache_read: number; cache_write: number }
export type SessionEvent =
  | { type: 'user'; text: string; attachments: string[]; at: number; source: SessionSource; /** Audio of a voice message sent directly. */ voice?: string[]; /** The web pages' ids of the message(s) it carries (SendMessageBody.client_id). */ client_ids?: string[]; /** Added to a running turn (Add to task): read at Claude's next step. */ injected?: boolean; /** Not typed by the owner (another session, an agent, a job, Harness): shown as a folded card (MessageCard). */ from?: MessageFrom; /** The part of the text for the owner when the rest is instructions for Claude. */ shown?: string; /** The @ it names (composer menu): drawn as chips. */ mentions?: SentMention[] }
  /** Transcript of the voice message just above (or why it failed). */
  | { type: 'voice_text'; text: string; error: string | null; stopped?: boolean; at: number }
  | { type: 'assistant'; text: string; at: number; /** Written by Claude Code in place of an answer, the API refused the call: why (rate_limit, server_error…). */ error?: string }
  | { type: 'thinking'; text: string; at: number }
  | { type: 'tool_use'; id: string; name: string; input: unknown; input_lines?: Record<string, number>; summary: string; at: number }
  | { type: 'tool_result'; tool_use_id: string; text: string; is_error: boolean; at: number }
  | { type: 'init'; model: string; cwd: string; at: number; /** A turn of a Claude process that already ran one: its background tasks run on. */ same?: boolean }
  | { type: 'result'; ok: boolean; cost_usd: number; duration_ms: number; model: string; usage: Usage; at: number }
  | { type: 'note'; text: string; level: 'info' | 'warn' | 'error'; at: number; /** The turn's process ended on a failure (its last lines). */ failed?: boolean }
  /** What turn `n` changed in git repositories (Changes view, features/code). */
  | ChangesEvent
  /** `ref` = `at` of a user event: hidden from the thread (or shown again). */
  | { type: 'hide'; ref: number; hidden: boolean; at: number }
  /** Background work of Claude Code (a sub-agent, a command): a partial update merged on `id`. */
  | TaskEvent
export type ChangesEvent = {
  type: 'changes'
  n: number
  repos: { root: string; name: string; branch: string | null; approx?: boolean; add: number; del: number; more?: number; files: { path: string; old: string | null; status: string; add: number; del: number; binary: boolean }[] }[]
  at: number
}
type TaskState = 'running' | 'completed' | 'failed' | 'stopped'
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
export type BusTopic = 'agents' | 'agents_layout' | 'agent-groups' | 'sessions' | 'workspace' | 'tasks' | 'crons' | 'telegram' | 'backup' | 'health' | 'extensions' | 'trash' | 'feed' | 'profile' | 'register' | 'license' | 'infra' | 'mcp' | 'team' | 'team_live' | 'approvals' | 'open_sessions' | 'browser' | 'devices' | 'jarvis' | 'webhooks'

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
export type FeedList = { events: FeedEvent[]; more: boolean; unread: number; unread_errors?: number; pending?: number; sources: { source: string; total: number; unread: number; unread_errors?: number }[] }
export type FeedRule = 'auto' | 'off' | 'silent' | 'loud'
export type FeedHookKind = 'stripe' | 'shopify' | 'github' | 'generic'
export type FeedHook = { id: string; name: string; kind: FeedHookKind; created: number; url: string; has_secret: boolean }
export type FeedSource = { source: string; label: string; builtin: boolean; rule: FeedRule; own_thread: boolean }
export type FeedSettings = { telegram: boolean; health: boolean; sources: FeedSource[]; hooks: FeedHook[]; kinds: FeedHookKind[]; rules: FeedRule[] }

/* ---------------------------------------------------------------- Webhooks & events (Settings -> Automate) */
export type WebhookSource = 'stripe' | 'shopify' | 'github' | 'generic' | 'phone'
export type WebhookTrigger =
  | { kind: 'in'; source: WebhookSource; methods: ('GET' | 'POST')[]; max_mb: number; reply: 'now' | 'wait'; filter?: { events?: string[]; branch?: string } }
  | { kind: 'event'; on: 'feed'; source?: string; levels?: string[]; contains?: string }
  | { kind: 'event'; on: 'agent' | 'cron'; agent?: string; cron?: string; when: 'any' | 'ok' | 'fail' }
export type WebhookAction =
  | { kind: 'shell'; command: string; cwd?: string; timeout_s: number }
  | { kind: 'call'; url: string; method: string; headers: Record<string, string>; body: string; sign: boolean; retries: number; timeout_s: number }
  | { kind: 'store'; fields: Record<string, string>; keep: number }
  | { kind: 'notify'; level?: string; title?: string; body?: string; url?: string }
export type WebhookCallStatus = 'queued' | 'running' | 'ok' | 'failed' | 'ignored'
export type WebhookCall = {
  id: string
  at: number
  trigger: 'in' | 'event' | 'test' | 'replay'
  event: string
  summary: string
  status: WebhookCallStatus
  http?: number
  exit?: number
  duration_s?: number
  output?: string
  error?: string
  attempts?: number
  of?: string
}
export type WebhookCallDetail = WebhookCall & {
  request: { method?: string; content_type?: string; headers?: Record<string, string>; query?: Record<string, unknown>; event?: string; files?: { field: string; name: string; path: string; size: number }[]; size?: number }
  body?: string
  body_truncated?: boolean
}
export type WebhookDataStats = { rows: number; today: number; days: number[]; last_id: number }
export type Webhook = {
  id: string
  name: string
  description: string
  enabled: boolean
  created: number
  updated?: number
  owner: string | null
  trigger: WebhookTrigger
  action: WebhookAction
  queue: { parallel: number; max_waiting: number }
  report: 'never' | 'fail' | 'always'
  url: string
  has_secret: boolean
  has_sign: boolean
  needs_secret: boolean
  last_call: WebhookCall | null
  calls_24h: number
  waiting: number
  data?: WebhookDataStats
}
export type FeedHookRef = { id: string; name: string; kind: FeedHookKind; url: string; has_secret: boolean; created: number; agent: string | null }
export type WebhooksPayload = { hooks: Webhook[]; feed_hooks: FeedHookRef[]; https: boolean }
export type WebhookRow = { id: number; at: number; call: string; data: unknown; fields?: Record<string, unknown> }
export type WebhookData = { rows: WebhookRow[]; stats: WebhookDataStats }

/* ---------------------------------------------------------------- Import */
export type ImportAgent = 'hermes' | 'claude-code' | 'openclaw' | 'other'
type ImportTopic = { name: string; source: string; files: number; exists: boolean }
type ImportProject = { name: string; exists: boolean; topics: ImportTopic[] }
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
/** An office document read by the server: text and slides as Markdown, a spreadsheet as the rows of its sheets. */
export type FileSheet = { name: string; rows: string[][]; truncated: boolean }
export type FileDoc = { path: string; mtime: number; size: number; truncated: boolean } & (
  | { type: 'text' | 'slides'; markdown: string }
  | { type: 'sheets'; sheets: FileSheet[] }
)
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
type CronTrigger = 'manual' | 'schedule' | 'catch-up' | 'retry'
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
type ExternalCron = { schedule: string; command: string; human: string }
export type CronsPayload = { jobs: Cron[]; external: ExternalCron[] }
export type CronPreview = { valid: boolean; human: string; next: number[]; error?: string; once?: boolean }

/* ---------------------------------------------------------------- Telegram */
type TelegramBot = { id: number; username: string; name: string }
type TelegramChat = { id: number; title: string; type: string }
/** Special threads have a path ('#crons', '#alerts'); session threads a session_id. */
type TelegramThread = { path: string; thread_id: number; name: string; session_id?: string }
/** simple = one chat (alerts + sessions as replies); threads = one thread per open session; mirror = threads + web turns copied. */
export type TelegramMode = 'simple' | 'threads' | 'mirror'
export type TelegramSettings = { mode: TelegramMode; notify_crons: boolean; notify_system: boolean; login_alerts: boolean; two_factor?: boolean; reply_mode: 'final' | 'progress'; thread_days: number; mirror_web: boolean }
export type DeviceOs = 'linux' | 'darwin' | 'windows' | 'android'
/** A device running Harness Link (api/devices.py): its record + what its connection says now. */
export type Device = {
  id: string
  name: string
  os: DeviceOs
  os_name: string
  kind: 'desktop' | 'android'
  arch: string
  version: string
  created: number
  last_seen: number
  /** false: it paired with a code and waits for the user's Accept / Refuse */
  confirmed: boolean
  /** view: Claude looks and guides; control: it clicks and types */
  mode: 'view' | 'control'
  /** ["*"] every project and agent, else "project:<name>" / "agent:<path>" */
  scope: string[]
  caps: string[]
  screen: { w: number; h: number; scale?: number } | null
  note: string
  ip: string
  online: boolean
  paused: boolean
  /** the person has it (live view) */
  human: boolean
  /** Claude acted on it in the last seconds */
  claude: boolean
  used_by: { session: string; owner: string; at: number } | null
  watched: boolean
  hello: { v: string; os: string; arch: string; caps: string[]; screen: { w: number; h: number; scale?: number } | null; note: string; screens?: DeviceScreen[]; display?: number | null } | null
  /** the screen chosen (index in hello.screens), -1 / absent = the main one */
  display?: number
  /** the screens as the app last described them (kept while it is offline) */
  screens?: DeviceScreen[]
}
type DeviceScreen = { i: number; name: string; w: number; h: number; main: boolean }
export type DeviceAsk = { id: string; session: string; owner: string; device: string; device_name: string; message: string; at: number; expires: number; status: string; note?: string }
export type DeviceAction = { at: number; device: string; tool: string; args: Record<string, string>; ok: boolean; ms: number; session: string; owner: string; error?: string }
export type DevicesStatus = {
  feature: boolean
  /** download targets this server can hand out (linux-amd64, …, android) */
  available: string[]
  latest: string
  devices: Device[]
  invites: { os: string; expires_at: number }[]
  asks: DeviceAsk[]
  actions: DeviceAction[]
}
export type DeviceInvite = {
  code: string
  os: string
  expires_at: number
  expires_in: number
  server: string
  commands: { sh: string; ps1: string }
  /** the phone's page (QR code) */
  link: string
  deeplink: string
  downloads: Record<string, string>
}
export type SessionDevices = { using: { id: string; name: string; os: DeviceOs; online: boolean; human: boolean; at: number }[]; asks: DeviceAsk[] }

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
/** `photo`: version of the profile photo ("" = none); `photo_url`: where to show it (wins over emoji and initials). */
export type Profile = { name: string; color: ProfileColor | ''; emoji: string; photo?: string; photo_url?: string }
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
  /** Settings -> Usage: $ per day for the whole server (0 = no budget); once reached, scheduled jobs and agents wait for the next day */
  daily_budget_usd?: number
  limit_retry?: boolean
  limit_retry_delay_s?: number
  usage_widget: boolean
  /** Settings -> Features: the Tasks page (/tasks), its sidebar entry and dashboard widget (off when new) */
  tasks_page?: boolean
  /** Settings -> Features: the Git & GitHub page (/git) and its sidebar entry */
  git_page: boolean
  /** Settings -> Features -> Sessions -> Code mode: the terminal (read-only here: POST /api/term/enable with the password, /disable). */
  code_mode?: boolean
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
  /** Settings -> System: CPU priorities (the UI first, then turns, then jobs and `maxxing heavy`), default on */
  cpu_priorities?: boolean
  /** Sidebar pages in the order the user dragged them (routes, e.g. "/sessions"); empty = the default order. */
  sidebar_order?: string[]
  nav_badges_hidden?: string[]   // Settings -> Features -> Badges: sidebar pages whose counter badge is off
  /** Settings -> Features: the Harness Browser (each topic / agent may then be let use it) */
  browser_feature?: boolean
  /** Settings -> Features: Devices (Claude uses the person's computers and phones running Harness Link) */
  devices_feature?: boolean
  /** Settings -> Features: Jarvis (one assistant who runs Harness: /jarvis) */
  jarvis_feature?: boolean
  /** memory-compaction line limit per memory.md (0 = none). */
  memory_max_lines: number
  /** Parts of the line under each answer that are hidden (every browser of the installation). */
  result_line_hidden?: ResultField[]
  /** Settings -> About: hide the donation links of What's new, Feedback and License (every browser). */
  donation_hidden?: boolean
}
export type ResultField = 'model' | 'duration' | 'cost' | 'tokens' | 'cache'

/* ---------------------------------------------------------------- Memory, stats, changelog */
type MemoryFile = { path: string; level: 'global' | 'project' | 'topic'; lines: number; bytes: number; over: boolean; heavy?: boolean }
export type MemoryInfo = { max_lines: number; max_bytes?: number; files: MemoryFile[] }
export type TokenCounts = { input: number; output: number; cache_read: number; cache_write: number; total: number; cost_usd: number; turns: number; sessions: number }
export type TokenStats = {
  totals: TokenCounts
  projects: (TokenCounts & { name: string })[]
  topics: (TokenCounts & { path: string })[]
  /** One row per agent folder (what `topics` counts for it), with its own last 30 days. */
  agents?: (TokenCounts & { path: string; name: string; label: string; days: { date: string; tokens: number; cost_usd: number }[] })[]
  sessions: (Omit<TokenCounts, 'sessions'> & { id: string; title: string; path: string; archived: boolean; updated: number })[]
  days: { date: string; tokens: number; cost_usd: number }[]
  /** Recent turns: median seconds until Claude Code's first event (start) and its first answer. */
  latency?: { start_s: number | null; first_answer_s: number | null; turns: number }
  at: number
}
export type ChangelogEntry = { version: string; label: string; current: boolean; body: string }
export type Changelog = { version: string; entries: ChangelogEntry[] }
export type Secret = { name: string; note: string; expose: boolean; /** projects / topics the key is given to; [] = every topic */ topics?: string[]; updated: number; preview: string }
/** A file of the Keys vault: only its description, the content never reaches the browser. */
export type SecretFile = { name: string; filename: string; size: number; sha256: string; note: string; expose: boolean; topics?: string[]; updated: number }
export type SecretFilePutBody = { file?: File; note?: string; expose?: boolean; topics?: string[]; create?: boolean }
export type SecretPutBody = { value?: string; note?: string; expose?: boolean; topics?: string[]; create?: boolean }

/* ---------------------------------------------------------------- System */
/** `seen`: marked as seen - it does not count in the sidebar until it changes or for 24 h. */
export type HealthIssue = { level: 'info' | 'warn' | 'error'; code: string; text: string; id?: string; seen?: boolean }
export type Health = {
  ok: boolean
  issues: HealthIssue[]
  /** null when the server could not read /proc/stat */
  cpu_pct: number | null
  /** `some` line of /proc/pressure/cpu: share of time programs waited for the processor (null without PSI) */
  cpu_pressure?: CpuPressure | null
  /** pressure avg10 >= 20 %: the CPU meter says "waiting" */
  cpu_waiting?: boolean
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
type CpuPressure = { avg10: number; avg60: number; avg300: number }
type CpuLevel = 'live' | 'normal' | 'background' | 'other'
type CpuKind = 'harness' | 'session' | 'agent' | 'heavy' | 'job' | 'browser' | 'docker' | 'other'
/** GET /api/system/cpu: CPU priorities and the units that use the processor most (`maxxing/cpu.py`). */
export type CpuSnapshot = {
  enabled: boolean
  pressure: CpuPressure | null
  waiting: boolean
  top: { unit: string; kind: CpuKind; name: string; label: string; level: CpuLevel; pct: number }[]
  at: number
}
export type Service = { name: string; label: string; active: boolean; enabled: boolean; since: number | null; state: string }
export type ServiceAction = 'start' | 'stop' | 'restart'
export type LogsPayload = { lines: string[]; /** a search only: lines that match, journal lines read, and whether the journal held more than was read */ matched?: number; scanned?: number; truncated?: boolean }
export type LogFilters = { since: string; level: string; q: string }
/** GET /metrics (Prometheus): its switch; `token` only in the answer that created it. */
export type MetricsStatus = { enabled: boolean; has_token: boolean; url: string; token?: string | null }
/** What a turn did (GET /api/sessions/{id}/turns): see docs/dev/API.md. */
export type TurnInfo = {
  n: number; at: number | null; prompt: string; state: 'done' | 'failed' | 'stopped' | 'timed_out' | 'running'; duration_s: number | null
  cost_usd: number | null; model: string; tokens: { input: number; output: number; cache_read: number; cache_write: number }; total_tokens: number
  model_calls: number; tool_calls: number; errors: number
}
export type TurnStep =
  | { kind: 'model'; at: number | null; model: string; context: number; cache_read: number; cache_write: number; text_chars: number; thinking: boolean; sub: boolean }
  | { kind: 'tool'; at: number | null; name: string; summary: string; duration_s: number | null; error: boolean; done: boolean; sub: boolean }
  | { kind: 'note'; at: number | null; level: string; text: string }
export type TurnDetail = TurnInfo & { steps: TurnStep[]; steps_dropped: number }
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
  auto_update?: {
    enabled: boolean
    tried?: { target: string; version?: string; at: number } | null
    last_check?: { at: number; verdict: string } | null
    /** What its last pass decided (`result`: started, busy, up_to_date, needs_review...; `why`: what a busy server waits for). */
    last?: { at: number; result: string; why?: string } | null
  }
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
  /** the customized web UI built on the new version (only when a customization changes it) */
  ui_build?: { status: 'ok' | 'failed' | 'unchecked' | 'pending'; reason?: 'never_built' | 'tools_changed'; error: string; seconds?: number }
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
type TimelineEvent = { at: number; state?: 'ok' | 'error' | 'running' | 'planned'; label?: string }
export type TimelineBlock = {
  type: 'timeline'
  start: number
  end: number
  now?: number
  lanes: { name: string; sub?: string; color?: string; dense?: boolean; href?: string; events: TimelineEvent[] }[]
  more?: string | null
}
type Card = {
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
  /** place among the pinned pages of the sidebar (null when not pinned) */
  pin_order?: number | null
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
type GitHubAccount = { login: string; name: string | null; avatar: string | null; keys: string[]; repos: number }
export type GitOverview = {
  root: string
  local: GitLocalRepo[]
  /** every account behind the server's GitHub tokens (any vault key holding one), merged */
  github: { connected: boolean; login: string | null; accounts: GitHubAccount[]; errors: { key: string; error: string }[]; error: string | null; repos: GitHubRepo[] }
}
type GitGraphRepo = Partial<GitLocalRepo> & {
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
export type GitPull = { number: number; title: string; author: string | null; head: string | null; base: string | null; draft: boolean; url: string; updated: number; state?: 'open' | 'closed' | 'merged'; /** By someone who is not owner, member or collaborator. */ outside?: boolean; /** A review is asked from one of the server's GitHub accounts. */ review_me?: boolean }

/* ---------------------------------------------------------------- Infra (server/maxxing/infra) */
export type InfraKind = 'server' | 'site' | 'worker' | 'pages' | 'database' | 'bucket' | 'domain'
export type InfraStatus = 'ok' | 'warn' | 'down' | 'unknown'
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
type MailCheck = { at: number; ok: boolean; error: string }
export type MailRight = 'read' | 'draft' | 'move' | 'mark' | 'send'
export type MailApproveSend = 'always' | 'new' | 'never'
export type MailTrigger = { enabled: boolean; folder: string; subject: string; senders: string[]; prompt: string }
/** An agent's access to one mailbox (agent.json `mail`): nothing by default. `senders` empty = all mail; else only
 *  mail whose sender the provider checked, and the agent writes only to them. */
export type MailGrant = { account: string; rights: MailRight[]; senders: string[]; approve_send: MailApproveSend; trigger: MailTrigger | null }
/** A grant as sent (POST / PATCH /api/agents): the server fills the trigger's missing fields. */
type MailGrantInput = Omit<MailGrant, 'trigger'> & { trigger: Partial<MailTrigger> | null }
type MailAgentGrant = Omit<MailGrant, 'account'> & { agent: string; name: string; avatar: AgentAvatar | null; enabled: boolean }
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
  /** hidden copies: shown to the owner before the send like the others */
  bcc?: string[]
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
type MailServerSettings = Pick<MailAccount, 'imap_host' | 'imap_port' | 'imap_tls' | 'smtp_host' | 'smtp_port' | 'smtp_tls'>
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

// ---- the Harness Browser (api/browser.py) ---------------------------------------------------------------------------
/** A project's / topic's (.maxxing.json) or an agent's (agent.json) own `browser` block: `enabled` is inherited
 *  topic -> project (an agent's never is); `profile` is an agent's choice only (else its project's). */
type BrowserSwitch = { enabled?: boolean; profile?: string }
/** Global settings (config.json -> browser; profiles and exits apart). */
export type BrowserSettings = {
  /** ask_human: Claude may ask the user to take over (captcha, sign-in); waits `wait_min` minutes */
  ask: boolean
  wait_min: number
  downloads: boolean
  /** minutes without use before a profile sleeps / a tab sleeps; tabs awake at most per profile */
  idle_min: number
  tab_sleep_min: number
  max_tabs: number
  /** profiles running at once (the oldest unused one sleeps) */
  max_active_profiles: number
  /** seconds a tool waits for a down exit before saying so */
  exit_wait_s: number
  /** the address bar's search engine */
  search: 'google' | 'duckduckgo' | 'bing'
}
/** A profile: its own Chromium (sign-ins) and its exit. `main` always exists (name "" = "Personal");
 *  one per project (made at its first use, or when the project has agents). */
export type BrowserProfile = {
  id: string
  name: string
  /** an exit id, or "direct" (the server's address) */
  exit: string
  /** exit down: wait (default) or go out by the server's address */
  on_exit_down: 'wait' | 'vps'
  /** the project this profile is for (`projects/<name>`), "" for the others */
  project: string
}
type BrowserProfileRow = BrowserProfile & {
  state: 'starting' | 'running' | 'stopped'
  tabs: number
  awake: number
  mem: number
  turns: number
  control: boolean
  asks: boolean
  /** its Chromium folder exists (sign-ins may be saved) */
  has_data: boolean
  /** a project's profile whose project was deleted */
  gone: boolean
  /** agents whose browser is on and runs on it */
  agents: number
}
export type BrowserExitKind = 'proxy' | 'tailscale' | 'wireguard'
/** What the sites see through an exit (ip-api.com through it), its delay and speed. */
export type BrowserExitTest = {
  ok: boolean
  error?: string
  at: number
  ip?: string
  country?: string
  country_code?: string
  city?: string
  operator?: string
  asn?: string
  /** isp: a home / office provider; mobile: a phone network; hosting: a datacenter (often blocked) */
  kind?: 'isp' | 'mobile' | 'hosting'
  latency_ms?: number
  mbps?: number
}
export type BrowserExit = {
  id: string
  name: string
  type: BrowserExitKind
  url?: string
  user?: string
  node?: string
  login_server?: string
  state: 'up' | 'down' | 'unknown'
  since: number | null
  error: string
  latency_ms: number | null
  test: BrowserExitTest | null
  /** being checked in the background right now (someone is looking at it) */
  checking?: boolean
  /** its password / config / auth key is in the vault */
  secret: boolean
}
type TailscaleNode = { id: string; name: string; dns: string; os: string; online: boolean; active: boolean }
export type TailscaleStatus = {
  state: 'needs_setup' | 'needs_login' | 'starting' | 'no_node' | 'node_offline' | 'up'
  auth_url?: string
  account?: string
  nodes?: TailscaleNode[]
  node?: TailscaleNode | null
  /** online in the account but not offered as an exit (not approved in the Tailscale console yet) */
  unapproved?: { name: string; os: string }[]
  error?: string
}
export type BrowserTab = {
  key: string
  url: string
  title: string
  /** who opened it */
  by: { kind: 'you' | 'session' | 'agent'; sid?: string; name?: string; path?: string }
  asleep: boolean
  /** shown in the live view */
  front: boolean
  used: number
  /** the navigator it belongs to (me, agent:<path>, session:<sid>) */
  nav: string
}
/** One profile's browser (running or not), or one navigator of it (`nav`: then only its tabs, its page...). */
export type BrowserState = {
  profile: string
  nav: string | null
  state: 'starting' | 'running' | 'stopped'
  started: number | null
  last_use: number | null
  /** when it sleeps if nothing uses it (Unix seconds) */
  stops_at: number | null
  tabs: BrowserTab[]
  /** the key of the tab shown */
  front: string | null
  page: { url: string; title: string } | null
  /** the person has the tab shown */
  control: boolean
  control_by: string | null
  /** Claude acted on the tab shown a moment ago */
  busy: boolean
  /** turns using it now */
  turns: { session: string; path: string; kind: 'session' | 'agent'; nav: string }[]
  /** bytes of memory of its Chromium */
  mem: number
  /** its CPU priority now: live (watched / Claude acts) or background */
  level: '' | 'live' | 'background'
  bytes: number
  /** hosts the proxy refused lately */
  blocked: string[]
  /** an alert / confirm / prompt open on the page shown: the person answers it */
  dialog: { type: 'alert' | 'confirm' | 'prompt' | 'beforeunload'; message: string; default: string } | null
  /** the page asked for files (a file input was clicked) */
  chooser: { multiple: boolean } | null
}
export type BrowserAsk = {
  id: string
  session: string
  owner: string
  profile?: string
  reason: string
  what: 'captcha' | 'sign_in' | 'code' | 'payment' | 'consent' | 'other'
  at: number
  expires: number
  status: 'pending' | 'done' | 'skip' | 'timeout' | 'expired'
}
type BrowserAction = {
  at: number
  session: string
  tool: string
  args: Record<string, unknown>
  ok: boolean
  ms?: number
  page?: string
  refused?: string
}
/** A turn stopped because its profile's exit went down (the session's card). */
type BrowserWaiter = { session: string; owner: string; exit: string; profile: string; at: number; resume: boolean }
/** A navigator = a window of tabs in a profile's Chromium: the person's ("me"), an agent's (lasting), a session's
 *  (temporary). Several may share a profile (its sign-ins); each sees only its own tabs. */
export type BrowserNavigator = {
  id: string
  kind: 'person' | 'agent' | 'session'
  /** the person's name for it, the agent's name, the session's title */
  name: string
  path?: string
  session?: string
  /** the profile it uses (null: an agent whose profile is gone) */
  profile: string | null
  running: boolean
  tabs: number
  awake: number
  page: { url: string; title: string } | null
  /** the person has its tab shown */
  control: boolean
  /** a live view shows it now */
  watched: boolean
  turns: number
  used: number
}
export type BrowserStatus = {
  feature: boolean
  navigators: BrowserNavigator[]
  settings: BrowserSettings
  available: { ok: boolean; missing: string[] }
  /** the exits' tools are on this server */
  tools: { tailscale: boolean; wireguard: boolean }
  setup: { running: boolean; log: string[]; error: string | null }
  profiles: BrowserProfileRow[]
  exits: BrowserExit[]
  direct: { test: BrowserExitTest | null; checking?: boolean }
  /** turns: session id -> the profile it uses now */
  summary: { running: string[]; mem: number; turns: Record<string, string>; tabs: Record<string, number>; cap: number; server_used: number; server_total: number; level: 'ok' | 'warn' | 'critical' }
  asks: BrowserAsk[]
  waiting: BrowserWaiter[]
}
/** A line of a profile's journal of temporary navigators (a session's): its sites, when, how much. */
export type BrowserSessionLine = {
  session: string
  title: string
  path: string
  first: number
  last: number
  actions: number
  sites: string[]
  /** its tabs are still open */
  open: boolean
  turns: number
}
export type BrowserProfileView = {
  profile: BrowserProfile
  browser: BrowserState
  gone: boolean
  /** the agents' navigators on it (lasting) */
  agents: BrowserNavigator[]
  /** the person's navigator, when it is on it */
  person: BrowserNavigator[]
  /** the sessions' navigators (temporary): a journal */
  temporary: BrowserSessionLine[]
  actions: BrowserAction[]
  asks: BrowserAsk[]
}
/** A project / topic / agent and the browser: what it sets itself, what it gets and where from. */
export type BrowserOwner = {
  owner: string
  path: string
  kind: 'project' | 'topic' | 'agent'
  own: BrowserSwitch
  enabled: boolean
  profile: string
  /** the owner that set it ("" = the default) */
  from: { enabled: string; profile: string }
  feature: boolean
  /** what it would get without its own block (its parent's) */
  inherited: { enabled: boolean; profile: string; from: { enabled: string; profile: string } } | null
  chain: string[]
  exit: BrowserExit | null
  /** its project (`projects/<name>`) and that project's profile ("" while never made) */
  project: string
  project_profile: string
  /** a sandboxed agent's domains (the only sites its browser opens); null = any public site */
  sites: string[] | null
  asks: BrowserAsk[]
}

/** Settings -> System -> Disk space (GET /api/system/cleanup): what Harness can free by itself, measured only. */
export type CleanupPartId = 'leftovers' | 'caches' | 'journal' | 'apt' | 'previews' | 'trash'
interface CleanupPart {
  id: CleanupPartId
  bytes: number
  /** ticked when the dialog opens (the trash never is: what is in it can still be restored) */
  default: boolean
  items: { path: string; why: string; bytes: number }[]
}
export interface CleanupScan {
  parts: CleanupPart[]
  disk: { total: number; free: number; pct: number }
}
export interface CleanupResult {
  freed: number
  parts: { id: CleanupPartId; freed: number; error?: string }[]
  disk: { total: number; free: number; pct: number }
}

/* ---------------------------------------------------------------- Jarvis (Settings -> Features -> jarvis_feature) */
type JarvisWorkState = 'running' | 'replied' | 'failed' | 'closed'
/** One piece of work Jarvis handed to a session (server jarvis.py work board). */
/** Who sent a message from another session's turn (log line `from`). */
/** Who sent a message the owner did not type (runner._sender): drawn as a folded card (MessageCard). */
export type MessageFromKind = 'session' | 'agent' | 'cron' | 'feed' | 'mail' | 'group' | 'manual' | 'cli' | 'github' | 'system'
export interface MessageFrom {
  kind: MessageFromKind
  /** the session that sent it (kind session / agent) */
  session?: string
  /** its name: session title, agent, job, group, or what asked for a run */
  title?: string
  /** the sender's path (topic, agent, group) */
  path?: string
  /** reports of Jarvis's work board read in this message */
  reports?: { id: number; outcome: 'done' | 'asks' | 'failed' }[]
}
export interface JarvisWork {
  id: number
  session: string
  path: string
  title: string
  brief: string
  state: JarvisWorkState
  created: number
  updated: number
  result: string
  cost: number
  /** its last answer ends on a question: it waits for the owner */
  question: boolean
  turns: number
  /** closed and its session archived by Harness (one Jarvis started, where the owner never wrote) */
  archived?: boolean
  /** why Jarvis started a new session although the topic had ones that could take the work */
  fresh?: string
}
export interface JarvisSettings {
  model: string
  dream_model: string
  root: boolean
  ask_first: boolean
  internals: boolean
  daily: boolean
  brief: string
  dream: string
  /** its conversation is summarized past this context; 0 = as every session */
  compact_tokens: number
  /** its answers on Telegram: the brief, questions and failures (important), every answer (all), none (off) */
  telegram: 'off' | 'important' | 'all'
  /** new work on the same subject continues a recent session of the topic */
  reuse: boolean
  /** closed work: its session is archived when Jarvis started it and the owner never wrote in it */
  archive_done: boolean
}
export interface JarvisStatus {
  on: boolean
  path: string
  session: Session | null
  settings: JarvisSettings
  last_brief: string
  last_dream: string
  work: JarvisWork[]
  open: number
  asks: number
  conversations: { id: string; title: string; updated: number; state: string; current: boolean }[]
}
