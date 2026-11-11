// Every React Query key used by the app. Keys start with a *domain* string so the global SSE
// bus (/api/stream) can invalidate a whole domain at once (see BUS_KEYS below).
import type { BusTopic } from '../types'

export const qk = {
  authState: ['auth', 'state'] as const,
  authMethods: ['auth', 'methods'] as const,
  onboarding: ['onboarding'] as const,
  claude: ['claude', 'status'] as const,
  workspace: ['workspace', 'tree'] as const,
  sessions: {
    all: ['sessions'] as const,
    list: (path?: string | null, archived?: boolean) => ['sessions', 'list', path ?? null, archived ?? false] as const,
    one: (id: string) => ['sessions', 'one', id] as const,
    events: (id: string) => ['sessions', 'events', id] as const,
    search: (q: string) => ['sessions', 'search', q] as const,
  },
  files: {
    all: ['files'] as const,
    list: (path: string) => ['files', 'list', path] as const,
    read: (path: string) => ['files', 'read', path] as const,
    search: (q: string) => ['files', 'search', q] as const,
  },
  tasks: ['tasks'] as const,
  packs: ['workspace', 'packs'] as const,
  skills: ['workspace', 'skills'] as const,
  crons: {
    all: ['crons'] as const,
    list: ['crons', 'list'] as const,
    runs: (cronId?: string | null, limit?: number) => ['crons', 'runs', cronId ?? null, limit ?? 50] as const,
    preview: (schedule: string) => ['crons', 'preview', schedule] as const,
  },
  telegram: {
    all: ['telegram'] as const,
    status: ['telegram', 'status'] as const,
    link: ['telegram', 'link'] as const,
  },
  pc: ['pc'] as const,
  backup: {
    all: ['backup'] as const,
    status: ['backup', 'status'] as const,
    history: ['backup', 'history'] as const,
  },
  settings: ['settings'] as const,
  profile: ['settings', 'profile'] as const,
  register: ['settings', 'register'] as const,
  feedback: ['settings', 'feedback'] as const,
  license: ['settings', 'license'] as const,
  secrets: ['secrets'] as const,
  secretFiles: ['secret-files'] as const,
  health: ['health'] as const,
  system: {
    services: ['system', 'services'] as const,
    logs: (unit: string, lines: number) => ['system', 'logs', unit, lines] as const,
    version: ['system', 'version'] as const,
    usage: ['system', 'usage'] as const,
    changelog: ['system', 'changelog'] as const,
    preflight: ['system', 'preflight'] as const,
  },
  memory: ['memory'] as const,
  stats: { tokens: ['stats', 'tokens'] as const },
  docs: {
    list: ['docs', 'list'] as const,
    full: ['docs', 'full'] as const,
    page: (slug: string) => ['docs', 'page', slug] as const,
  },
  dashboard: {
    all: ['dashboard'] as const,
    widget: (id: string) => ['dashboard', 'widget', id] as const,
  },
  extensions: ['extensions'] as const,
  trash: ['trash'] as const,
  feed: {
    all: ['feed'] as const,
    list: (source: string | null, unread: boolean, limit: number) => ['feed', 'list', source, unread, limit] as const,
    pages: (source: string | null, unread: boolean, pending = false) => ['feed', 'pages', source, unread, pending] as const,
    settings: ['feed', 'settings'] as const,
  },
}

/** Global bus topic → query key prefixes to invalidate (minus what `busSkips` leaves to the streams). */
export const BUS_KEYS: Record<BusTopic, readonly (readonly unknown[])[]> = {
  // The tree's counters (running, unread, sessions) only change with events that also carry `workspace`.
  sessions: [qk.sessions.all],
  workspace: [qk.workspace, qk.onboarding, qk.memory],
  tasks: [qk.tasks],
  // an agent's page lists its cron jobs
  crons: [qk.crons.all, ['agents', 'one']],
  telegram: [qk.telegram.all, qk.onboarding, qk.authMethods],
  backup: [qk.backup.all, qk.onboarding],
  health: [qk.health, qk.system.services],
  extensions: [qk.extensions, qk.dashboard.all],
  trash: [qk.trash, qk.files.all],
  feed: [qk.feed.all],
  // Team shows the user's own face too
  profile: [qk.profile, ['team']],
  register: [qk.register, qk.onboarding],
  license: [qk.license, ['system']],
  infra: [['infra']],
  team: [['team']],
  // an agent was created, changed or removed (templates and the sandbox check do not move with it); the groups show
  // the names, faces and switches of their members
  agents: [['agents', 'list'], ['agents', 'one'], ['agents', 'thread'], ['agents', 'layout'], ['agent-groups', 'list'], ['agent-groups', 'one']],
  agents_layout: [['agents', 'layout']],
  // a group was created, changed or removed, or one of them spoke (its own topic below carries its messages)
  'agent-groups': [['agent-groups', 'list'], ['agent-groups', 'one']],
  /** someone started / stopped writing, came online: the list and the faces only */
  team_live: [['team', 'state']],
  mcp: [['mcp']],
  approvals: [['approvals']],
}

/** Query keys of one bus topic: `agents:<path>` = that agent's thread or unread changed (a message, a feed event
 *  of the agent, "seen"): the list's counters, its page and its thread, not every agent's. */
export function busKeysOf(topic: string): readonly (readonly unknown[])[] {
  if (topic.startsWith('agents:')) {
    const path = topic.slice(7)
    return [['agents', 'list'], ['agents', 'one', path], ['agents', 'thread', path]]
  }
  /** `agent-groups:<group path>` = that group's conversation or state (who speaks, paused members) changed. */
  if (topic.startsWith('agent-groups:')) {
    const path = topic.slice(13)
    return [['agent-groups', 'list'], ['agent-groups', 'one', path], ['agent-groups', 'messages', path]]
  }
  return BUS_KEYS[topic as BusTopic] || []
}

/** Data the bus keeps fresh on its own (file watchers + every write path): no refetch when the tab is shown
 *  again (useGlobalBus refreshes them once after a long absence instead). The dashboard is not in it (its
 *  widgets read crons, health, external services...). */
export const LIVE_KEYS: readonly (readonly unknown[])[] = [qk.sessions.all, qk.workspace, qk.tasks, qk.crons.all, qk.trash, qk.extensions, qk.health, qk.telegram.all, qk.backup.all]
export const isLiveKey = (key: readonly unknown[]) => LIVE_KEYS.some((p) => p.every((x, i) => key[i] === x))

/** Extra keys when one batch carries both `sessions` and `workspace`: the server pairs them when a session starts
 *  or ends a turn (state/unread change), appears or goes away. A turn may reveal an expired Claude sign-in and
 *  moves the token stats; plain `sessions` events (metadata while a turn streams, queue edits) do not. An agent's page
 *  shows its running sessions and what started them: a run started by another process (a schedule, `maxxing agents
 *  run`) only reaches it this way. */
export const BUS_TURN_KEYS: readonly (readonly unknown[])[] = [qk.claude, qk.stats.tokens, ['agents', 'one'], ['agents', 'thread']]

/** What the open streams keep fresh by themselves: `bus` = /api/stream is connected (useGlobalBus), `sessions` =
 *  ids whose own stream is connected (useSessionStream: its `state` frames carry the Session at every change). */
export const liveStreams = { bus: false, sessions: new Map<string, number>() }

/** Keys a bus batch leaves alone: the Session of a column whose stream is open (the stream already pushed it), and
 *  the session searches outside turn batches (a snapshot: only a finished turn adds text to find). */
export function busSkips(key: readonly unknown[], turn: boolean): boolean {
  if (key[0] !== 'sessions') return false
  if (key[1] === 'one') return liveStreams.sessions.has(key[2] as string)
  return key[1] === 'search' && !turn
}

/** For a write the server announces on the bus itself: nothing to invalidate while the bus is connected (it
 *  refetches the same keys a moment later; invalidating here too fetched everything twice), `keys` otherwise. */
export const unlessBus = (keys: readonly (readonly unknown[])[]) => () => (liveStreams.bus ? [] : keys)
