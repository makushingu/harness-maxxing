import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, seg } from '../api'
import type { AgentGroup, AgentGroupInput, AgentGroupMessage, Ok } from '../types'
import { qk } from './keys'
import { useMut } from './util'

// Agent groups (on the Agents page): the owner talks to 2-6 agents of one project, who answer in turn.
// The bus topic `agent-groups` refreshes the list and the groups, `agent-groups:<path>` one group and its messages.
export const groupKeys = {
  all: ['agent-groups'] as const,
  list: ['agent-groups', 'list'] as const,
  one: (path: string) => ['agent-groups', 'one', path] as const,
  messages: (path: string) => ['agent-groups', 'messages', path] as const,
}

/** "projects/acme/groups/writing" -> "/api/agent-groups/acme/writing" */
export const GROUP_PATH_RE = /^projects\/([^/]+)\/groups\/([^/]+)$/
export function groupUrl(path: string, sub = ''): string {
  const m = GROUP_PATH_RE.exec(path)
  if (!m) throw new Error(`Not a group path: ${path}`)
  return `/api/agent-groups/${seg(m[1])}/${seg(m[2])}${sub}`
}
/** Route of a group's page. */
export const groupRoute = (g: Pick<AgentGroup, 'project' | 'name'>) => `/agents/groups/${g.project}/${g.name}`
/** Route of the creation form (`project` prefilled). */
export const newGroupRoute = (project?: string) => `/agents/groups/new${project ? `?project=${encodeURIComponent(project)}` : ''}`

export function useAgentGroups(enabled = true) {
  return useQuery({ queryKey: groupKeys.list, queryFn: () => api.get<{ groups: AgentGroup[] }>('/api/agent-groups').then((r) => r.groups), enabled })
}
export function useAgentGroup(path: string | null) {
  return useQuery({ queryKey: groupKeys.one(path || ''), queryFn: () => api.get<AgentGroup>(groupUrl(path!)), enabled: !!path })
}
/** The last `limit` messages; once held, a refresh asks only for the ones after the last (`after`) and adds them. */
export function useGroupMessages(path: string | null, limit = 300) {
  const qc = useQueryClient()
  return useQuery({
    queryKey: groupKeys.messages(path || ''),
    queryFn: async () => {
      const held = qc.getQueryData<AgentGroupMessage[]>(groupKeys.messages(path!))
      const after = held?.length ? held[held.length - 1].at : undefined
      const r = await api.get<{ messages: AgentGroupMessage[] }>(groupUrl(path!, '/messages'), after != null ? { limit, after } : { limit })
      if (!held || after == null) return r.messages
      if (!r.messages.length) return held
      const ids = new Set(held.map((m) => m.id))
      return [...held, ...r.messages.filter((m) => !ids.has(m.id))].slice(-limit)
    },
    enabled: !!path,
  })
}

/** The group in the cache (its page, the list) as the server answered it. */
function usePutGroup() {
  const qc = useQueryClient()
  return (g: AgentGroup) => {
    qc.setQueryData(groupKeys.one(g.path), g)
    qc.setQueryData(groupKeys.list, (old: AgentGroup[] | undefined) => (old ? (old.some((x) => x.path === g.path) ? old.map((x) => (x.path === g.path ? g : x)) : [...old, g]) : old))
  }
}

// creating or deleting a group adds / removes a folder of the project
const inv = [groupKeys.all, qk.workspace] as const

/** `errorToast: false`: the form shows the refusal (members of another project, two @names alike, folder taken). */
export function useCreateGroup() {
  const put = usePutGroup()
  return useMut((b: AgentGroupInput) => api.post<AgentGroup>('/api/agent-groups', b), { onSuccess: put, invalidate: inv, errorToast: false })
}
export function usePatchGroup({ errorToast = true }: { errorToast?: boolean } = {}) {
  const put = usePutGroup()
  return useMut(({ path, ...b }: AgentGroupInput & { path: string }) => api.patch<AgentGroup>(groupUrl(path), b), { onSuccess: put, invalidate: [groupKeys.all], errorToast })
}
/** Its page and conversation leave the cache first: refetched, they would only say "not found" before the page goes. */
export function useDeleteGroup() {
  const qc = useQueryClient()
  return useMut(({ path, keep_files }: { path: string; keep_files?: boolean }) => api.del<Ok>(`${groupUrl(path)}${keep_files ? '?keep_files=true' : ''}`), {
    onSuccess: (_r, { path }) => {
      qc.removeQueries({ queryKey: groupKeys.one(path) })
      qc.removeQueries({ queryKey: groupKeys.messages(path) })
    },
    invalidate: inv,
  })
}
/** The owner's message: shown at once (the server's copy), the members' turns follow on the bus. */
export function useGroupSay() {
  const qc = useQueryClient()
  return useMut(
    ({ path, text }: { path: string; text: string }) => api.post<{ message: AgentGroupMessage; queued: string[] }>(groupUrl(path, '/messages'), { text }),
    {
      onSuccess: (r, { path }) => {
        qc.setQueryData(groupKeys.messages(path), (old: AgentGroupMessage[] | undefined) => (old && !old.some((m) => m.id === r.message.id) ? [...old, r.message] : old))
      },
      invalidate: [groupKeys.list, ['agent-groups', 'one']],
    },
  )
}
/** Stop: the queue is emptied and the turn in progress stopped. */
export function useGroupStop() {
  return useMut(({ path }: { path: string }) => api.post<Ok>(groupUrl(path, '/stop'), {}), { invalidate: [groupKeys.all] })
}
/** New topic: the members start fresh sessions (the conversation stays on screen). */
export function useGroupReset() {
  return useMut(({ path }: { path: string }) => api.post<Ok>(groupUrl(path, '/reset'), {}), { invalidate: [groupKeys.all] })
}
export function useGroupSeen() {
  return useMut(({ path }: { path: string }) => api.post<Ok>(groupUrl(path, '/seen'), {}), {
    invalidate: [groupKeys.list],
    errorToast: false,
    optimistic: ({ path }) => [
      { key: groupKeys.list, update: (d: AgentGroup[]) => d.map((g) => (g.path === path ? { ...g, unread: 0 } : g)) },
      { key: groupKeys.one(path), update: (g: AgentGroup) => ({ ...g, unread: 0 }) },
    ],
  })
}
/** Pause a member in the group (it does not speak until named again) or let it speak again. Instant. */
export function useGroupPause() {
  const put = usePutGroup()
  return useMut(
    ({ path, member, paused }: { path: string; member: string; paused: boolean }) => {
      const m = /^projects\/([^/]+)\/topics\/([^/]+)\/agents\/([^/]+)$/.exec(member)
      if (!m) throw new Error(`Not an agent path: ${member}`)
      return api.post<AgentGroup>(groupUrl(path, `/members/${seg(m[1])}/${seg(m[2])}/${seg(m[3])}/pause`), { paused })
    },
    {
      onSuccess: put,
      optimistic: ({ path, member, paused }) => {
        const patch = (g: AgentGroup) => (g.path === path ? { ...g, members: g.members.map((x) => (x.path === member ? { ...x, paused } : x)) } : g)
        return [
          { key: groupKeys.one(path), update: patch },
          { key: groupKeys.list, update: (d: AgentGroup[]) => d.map(patch) },
        ]
      },
    },
  )
}
