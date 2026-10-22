// Every React Query key used by the app. Keys start with a *domain* string so the global SSE
// bus (/api/stream) can invalidate a whole domain at once (see BUS_KEYS below).
import type { BusTopic } from '../types'

export const qk = {
  authState: ['auth', 'state'] as const,
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
  license: ['settings', 'license'] as const,
  secrets: ['secrets'] as const,
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
    pages: (source: string | null, unread: boolean) => ['feed', 'pages', source, unread] as const,
    settings: ['feed', 'settings'] as const,
  },
}

/** Global bus topic → query key prefixes to invalidate. */
export const BUS_KEYS: Record<BusTopic, readonly (readonly unknown[])[]> = {
  // The tree's counters (running, unread, sessions) only change with events that also carry `workspace`.
  sessions: [qk.sessions.all],
  workspace: [qk.workspace, qk.onboarding, qk.memory],
  tasks: [qk.tasks],
  crons: [qk.crons.all],
  telegram: [qk.telegram.all, qk.onboarding],
  backup: [qk.backup.all, qk.onboarding],
  health: [qk.health, qk.system.services],
  extensions: [qk.extensions, qk.dashboard.all],
  trash: [qk.trash, qk.files.all],
  feed: [qk.feed.all],
  profile: [qk.profile],
  register: [qk.register, qk.onboarding],
  license: [qk.license, ['system']],
  infra: [['infra']],
  mcp: [['mcp']],
}

/** Data the bus keeps fresh on its own (file watchers + every write path): no refetch when the tab is shown
 *  again (useGlobalBus refreshes them once after a long absence instead). The dashboard is not in it (its
 *  widgets read crons, health, external services...). */
export const LIVE_KEYS: readonly (readonly unknown[])[] = [qk.sessions.all, qk.workspace, qk.tasks, qk.crons.all, qk.trash, qk.extensions, qk.health, qk.telegram.all, qk.backup.all]
export const isLiveKey = (key: readonly unknown[]) => LIVE_KEYS.some((p) => p.every((x, i) => key[i] === x))

/** Extra keys when one batch carries both `sessions` and `workspace`: the server pairs them when a session starts
 *  or ends a turn (state/unread change), appears or goes away. A turn may reveal an expired Claude sign-in and
 *  moves the token stats; plain `sessions` events (metadata while a turn streams, queue edits) do not. */
export const BUS_TURN_KEYS: readonly (readonly unknown[])[] = [qk.claude, qk.stats.tokens]
