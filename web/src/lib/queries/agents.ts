import { useQuery } from '@tanstack/react-query'
import { api, seg } from '../api'
import type { Agent, AgentDetail, AgentInput, AgentMessage, AgentRunResult, AgentsPayload, AgentTemplate, AgentWebhookKind, AgentWebhookResult, Cron, FeedLevel, Ok } from '../types'
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
}

/** "projects/acme/topics/blog/agents/writer" -> "/api/agents/acme/blog/writer" */
export function agentUrl(path: string, sub = ''): string {
  const m = /^projects\/([^/]+)\/topics\/([^/]+)\/agents\/([^/]+)$/.exec(path)
  if (!m) throw new Error(`Not an agent path: ${path}`)
  return `/api/agents/${seg(m[1])}/${seg(m[2])}/${seg(m[3])}${sub}`
}
/** Route of an agent's page. */
export const agentRoute = (a: Pick<Agent, 'project' | 'topic' | 'name'>) => `/agents/${a.project}/${a.topic}/${a.name}`

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

export function useCreateAgent() {
  return useMut((b: AgentInput) => api.post<Agent>('/api/agents', b), { invalidate: inv, errorToast: false })
}
export function usePatchAgent() {
  return useMut(({ path, ...b }: AgentInput & { path: string }) => api.patch<Agent>(agentUrl(path), b), {
    // Switches and small edits show at once (list, detail); the bus / invalidation reconciles.
    optimistic: ({ path, ...b }) => {
      const patch = <T extends Agent>(a: T): T => {
        if (a.path !== path) return a
        const { display_name, avatar, limits, triggers: _t, ...rest } = b
        return {
          ...a,
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
