import { useQuery } from '@tanstack/react-query'
import { api, seg } from '../api'
import type {
  Agent, AgentDetail, AgentsLayout, AgentImportResult, AgentInput, AgentMessage, AgentRunResult, AgentSandboxStatus, AgentsPayload, AgentTemplate, AgentWebhookKind,
  AgentWebhookResult, Cron, FeedLevel, Ok, Session,
} from '../types'
import { qk } from './keys'
import { useMut } from './util'

// Agents (Settings -> Features -> agents_page): lasting roles living in a topic folder, with triggers.
// The bus topic `agents` refreshes every key below (BUS_KEYS); creating or deleting one also changes the workspace tree.
export const agentKeys = {
  all: ['agents'] as const,
  list: ['agents', 'list'] as const,
  one: (path: string) => ['agents', 'one', path] as const,
  thread: (path: string) => ['agents', 'thread', path] as const,
  templates: (lang: string) => ['agents', 'templates', lang] as const,
  sandbox: ['agents', 'sandbox'] as const,
  layout: ['agents', 'layout'] as const,
}

/** "projects/acme/topics/blog/agents/writer" -> "/api/agents/acme/blog/writer" */
export function agentUrl(path: string, sub = ''): string {
  const m = /^projects\/([^/]+)\/topics\/([^/]+)\/agents\/([^/]+)$/.exec(path)
  if (!m) throw new Error(`Not an agent path: ${path}`)
  return `/api/agents/${seg(m[1])}/${seg(m[2])}/${seg(m[3])}${sub}`
}
/** Route of an agent's page. */
export const agentRoute = (a: Pick<Agent, 'project' | 'topic' | 'name'>) => `/agents/${a.project}/${a.topic}/${a.name}`

/** An agent folder (projects/<p>/topics/<t>/agents/<name>): its sessions are the agent's runs. */
export const AGENT_PATH_RE = /^projects\/([^/]+)\/topics\/([^/]+)\/agents\/([^/]+)$/
/** A run of an agent: shown on the Agents page, never in Sessions. */
export const isAgentSession = (s: Pick<Session, 'path' | 'source'>) => s.source === 'agent' || AGENT_PATH_RE.test(s.path || '')
/** Route of one run of an agent (its session, opened in the Agents page). `path` = the agent path. */
export function agentRunRoute(path: string, sid: string): string {
  const m = AGENT_PATH_RE.exec(path)
  return m ? `/agents/${m[1]}/${m[2]}/${m[3]}/runs/${sid}` : `/agents`
}

export function useAgents(enabled = true) {
  return useQuery({ queryKey: agentKeys.list, queryFn: () => api.get<AgentsPayload>('/api/agents'), enabled })
}
/** The gallery of ready-made agents (texts in `lang`; `keys_present` = its suggested keys found in the vault). */
export function useAgentTemplates(lang: string, enabled = true) {
  return useQuery({
    queryKey: agentKeys.templates(lang),
    queryFn: () => api.get<{ templates: AgentTemplate[] }>('/api/agents/templates', { lang }).then((r) => r.templates),
    enabled,
    staleTime: 60_000,
  })
}
/** Everything to look at on the Agents page: new results plus approvals waiting (the nav badge). */
export function useAgentsAttention(enabled = true): number {
  const { data } = useAgents(enabled)
  return (data?.agents || []).reduce((n, a) => n + (a.thread_unread || 0) + (a.waiting || 0), 0)
}
/** What the sandbox of agents needs on this server (GET /api/agents/sandbox). */
export function useAgentSandbox(enabled = true) {
  return useQuery({ queryKey: agentKeys.sandbox, queryFn: () => api.get<AgentSandboxStatus>('/api/agents/sandbox'), enabled, staleTime: 60_000 })
}
export function useAgent(path: string | null) {
  return useQuery({ queryKey: agentKeys.one(path || ''), queryFn: () => api.get<AgentDetail>(agentUrl(path!)), enabled: !!path })
}
export function useAgentThread(path: string | null, limit = 200) {
  return useQuery({
    queryKey: agentKeys.thread(path || ''),
    queryFn: () => api.get<{ messages: AgentMessage[] }>(agentUrl(path!, '/thread'), { limit }),
    enabled: !!path,
  })
}

const inv = [agentKeys.all, qk.workspace] as const

/** The order of projects and agents and the project colours of the Agents page (shared by every device). */
export function useAgentsLayoutData(enabled = true) {
  return useQuery({ queryKey: agentKeys.layout, queryFn: () => api.get<AgentsLayout>('/api/agents/layout'), enabled, staleTime: 30_000 })
}
/** Saves the whole layout; the screen follows at once (put back if refused). */
export function useSaveAgentsLayout() {
  return useMut((b: AgentsLayout) => api.put<AgentsLayout>('/api/agents/layout', b), {
    optimistic: (b) => [{ key: agentKeys.layout, update: () => b }],
    invalidate: [agentKeys.layout],
  })
}

export function useCreateAgent() {
  return useMut((b: AgentInput) => api.post<Agent>('/api/agents', b), { invalidate: inv, errorToast: false })
}
/** `errorToast: false` = the caller shows the refusal under its field (bad_domain, bad_path, bad_rule). */
export function usePatchAgent({ errorToast = true }: { errorToast?: boolean } = {}) {
  return useMut(({ path, ...b }: AgentInput & { path: string }) => api.patch<Agent>(agentUrl(path), b), {
    errorToast,
    // One at a time: some fields (triggers) are sent whole, so a later edit must not land before an earlier one.
    scope: { id: 'agent-patch' },
    // Switches and small edits show at once (list, detail); the bus / invalidation reconciles.
    optimistic: ({ path, ...b }) => {
      const patch = <T extends Agent>(a: T): T => {
        if (a.path !== path) return a
        const { display_name, avatar, limits, triggers, ...rest } = b
        // Triggers already known (switched, edited, removed) show at once, so a second quick switch builds its
        // list from this one; a new trigger waits for the server (its id).
        const byId = new Map(a.triggers.map((x) => [x.id, x]))
        const known = triggers?.every((x) => x.id && byId.has(x.id))
        return {
          ...a,
          ...(triggers && known && { triggers: triggers.map((x) => ({ ...byId.get(x.id!)!, ...x, kind: 'feed' as const })) }),
          ...Object.fromEntries(Object.entries(rest).filter(([k]) => k in a)),
          ...(display_name !== undefined && { display_name }),
          ...(avatar && { avatar: { ...a.avatar, ...avatar } }),
          ...(limits && { limits: { ...a.limits, ...limits } }),
        }
      }
      return [
        { key: agentKeys.list, update: (d: { agents: Agent[] }) => ({ ...d, agents: d.agents.map(patch) }) },
        { key: agentKeys.one(path), update: (a: AgentDetail) => patch(a) },
      ]
    },
    invalidate: inv,
  })
}
export function useDeleteAgent() {
  return useMut((path: string) => api.del<Ok>(agentUrl(path)), { invalidate: inv })
}
export function useRunAgent() {
  return useMut(
    ({ path, text, reply_to }: { path: string; text?: string; reply_to?: string }) =>
      api.post<AgentRunResult>(agentUrl(path, '/run'), { text: text || undefined, reply_to: reply_to || undefined }),
    { invalidate: [agentKeys.all] },
  )
}
export function useAgentSeen() {
  return useMut(({ path }: { path: string }) => api.post<{ ok: boolean }>(agentUrl(path, '/seen'), {}), {
    invalidate: [agentKeys.all],
    errorToast: false,
  })
}
export function useTestAgentTrigger() {
  return useMut(({ path, tid }: { path: string; tid: string }) => api.post<{ event: unknown }>(agentUrl(path, `/triggers/${tid}/test`), {}), {
    invalidate: [agentKeys.all, qk.feed.all],
  })
}
export function useAddAgentWebhook() {
  return useMut(
    ({ path, ...b }: { path: string; kind: AgentWebhookKind; prompt?: string; levels?: FeedLevel[]; match?: string }) =>
      api.post<AgentWebhookResult>(agentUrl(path, '/webhook'), b),
    { invalidate: [agentKeys.all, qk.feed.all] },
  )
}
export function useAddAgentCron() {
  return useMut(
    ({ path, ...b }: { path: string; name?: string; schedule: string; prompt: string; enabled?: boolean }) => api.post<Cron>(agentUrl(path, '/crons'), b),
    { invalidate: [agentKeys.all, qk.crons.all], errorToast: false },
  )
}
/** "Continue in Sessions": a normal session of the topic with the run's history and Claude thread (409 while it runs). */
export function useContinueRun() {
  return useMut(({ path, sid }: { path: string; sid: string }) => api.post<{ session: Session }>(agentUrl(path, `/runs/${seg(sid)}/continue`), {}), {
    invalidate: [qk.sessions.all, qk.workspace],
  })
}
/** Create an agent from a Claude Code agent file (.claude/agents/<name>.md). */
export function useImportAgent() {
  return useMut((b: { topic_path: string; markdown: string; name?: string }) => api.post<AgentImportResult>('/api/agents/import', b), { invalidate: inv, errorToast: false })
}
/** The agent as a Claude Code agent file (a download). */
export const agentExportUrl = (path: string) => agentUrl(path, '/export')
