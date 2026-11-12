import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, seg } from '../api'
import type { DecisionItem, Enterprise, EnterpriseInput, EnterprisePatch, EnterpriseSummary, EnterpriseTemplate, InboxItem, Ok, PositionInput, PositionPatch } from '../types'
import { qk } from './keys'
import { useMut } from './util'

// Enterprises (Settings -> Features -> enterprises_page): an org chart of agents above projects.
// The bus topic `enterprises` refreshes everything, `enterprises:<slug>` one enterprise (chart, inboxes, decisions).
export const entKeys = {
  all: ['enterprises'] as const,
  list: ['enterprises', 'list'] as const,
  one: (id: string) => ['enterprises', 'one', id] as const,
  inbox: (id: string, pos: string) => ['enterprises', 'inbox', id, pos] as const,
  decisions: (id: string) => ['enterprises', 'decisions', id] as const,
  templates: ['enterprises', 'templates'] as const,
}

const base = (id: string, sub = '') => `/api/enterprises/${seg(id)}${sub}`
const posUrl = (id: string, pos: string, sub = '') => base(id, `/positions/${seg(pos)}${sub}`)

/** Route of an enterprise: its org chart, or one of its tabs. */
export const enterpriseRoute = (id: string, tab = '') => `/enterprises/${id}${tab && tab !== 'chart' ? `/${tab}` : ''}`

export function useEnterprises(enabled = true) {
  return useQuery({ queryKey: entKeys.list, queryFn: () => api.get<{ enterprises: EnterpriseSummary[] }>('/api/enterprises').then((r) => r.enterprises), enabled })
}
export function useEnterprise(id: string | null) {
  return useQuery({ queryKey: entKeys.one(id || ''), queryFn: () => api.get<Enterprise>(base(id!)), enabled: !!id })
}
/** The ready-made charts offered by New enterprise. */
export function useEnterpriseTemplates(enabled = true) {
  return useQuery({ queryKey: entKeys.templates, queryFn: () => api.get<{ templates: EnterpriseTemplate[] }>('/api/enterprises/templates').then((r) => r.templates), enabled, staleTime: 60_000 })
}
/** What waits in a position's inbox (deliveries, escalations, assignments), newest first as the server sends it. */
export function usePositionInbox(id: string | null, pos: string | null) {
  return useQuery({ queryKey: entKeys.inbox(id || '', pos || ''), queryFn: () => api.get<{ items: InboxItem[] }>(posUrl(id!, pos!, '/inbox')).then((r) => r.items), enabled: !!id && !!pos })
}
/** One page of the decision log; `before` = the `next` of the previous page. */
export function useEnterpriseDecisions(id: string | null, before?: number | null, limit = 50) {
  return useQuery({
    queryKey: [...entKeys.decisions(id || ''), before ?? null, limit],
    queryFn: () => api.get<{ items: DecisionItem[]; next: number | null }>(base(id!, '/decisions'), before != null ? { before, limit } : { limit }),
    enabled: !!id,
  })
}

/** The enterprise in the cache (its page, the list) as the server answered it. */
function usePutEnterprise() {
  const qc = useQueryClient()
  return (e: Enterprise) => qc.setQueryData(entKeys.one(e.id), e)
}

// creating, deleting or relinking an enterprise moves projects between "linked" and "free"; agents seat and leave
const inv = [entKeys.all, qk.workspace] as const

/** `errorToast: false`: the dialog shows the refusal (name, folder taken, project already linked). */
export function useCreateEnterprise() {
  const put = usePutEnterprise()
  return useMut((b: EnterpriseInput) => api.post<Enterprise>('/api/enterprises', b), { onSuccess: put, invalidate: inv, errorToast: false })
}
export function usePatchEnterprise({ errorToast = true }: { errorToast?: boolean } = {}) {
  const put = usePutEnterprise()
  return useMut(({ id, ...b }: EnterprisePatch & { id: string }) => api.patch<Enterprise>(base(id), b), { onSuccess: put, invalidate: [entKeys.list], errorToast })
}
export function useDeleteEnterprise() {
  const qc = useQueryClient()
  return useMut(({ id }: { id: string }) => api.del<Ok>(base(id)), {
    onSuccess: (_r, { id }) => {
      qc.removeQueries({ queryKey: entKeys.one(id) })
    },
    invalidate: inv,
  })
}
/** Link / unlink projects: `409 occupied` when positions are held by agents of an unlinked project (retry with `vacate`). */
export function usePutEnterpriseProjects() {
  const put = usePutEnterprise()
  return useMut(({ id, projects, vacate }: { id: string; projects: string[]; vacate?: boolean }) => api.put<Enterprise>(base(id, '/projects'), { projects, vacate: vacate || undefined }), {
    onSuccess: put,
    invalidate: inv,
    errorToast: false,
  })
}
/** `enterprise` = the enterprise's id, `id` = the new position's id. */
export function useAddPosition() {
  return useMut(({ enterprise, ...b }: PositionInput & { enterprise: string }) => api.post<Enterprise | Ok>(base(enterprise, '/positions'), b), { invalidate: [entKeys.all], errorToast: false })
}
/** `409 stale` = a structure change made on an old `rev`: the caller refetches and says so. */
export function usePatchPosition() {
  return useMut(({ id, pos, ...b }: PositionPatch & { id: string; pos: string }) => api.patch<Enterprise | Ok>(posUrl(id, pos), b), { invalidate: [entKeys.all], errorToast: false })
}
export function useDeletePosition() {
  return useMut(({ id, pos, reparent_to }: { id: string; pos: string; reparent_to?: string }) => api.del<Ok>(`${posUrl(id, pos)}${reparent_to ? `?reparent_to=${encodeURIComponent(reparent_to)}` : ''}`), { invalidate: [entKeys.all] })
}
/** Creates the agent in `topic` (a topic path, projects/<p>/topics/<t>) and seats it; the agent sets itself up in its conversation. */
export function useHirePosition() {
  return useMut(({ id, pos, topic }: { id: string; pos: string; topic: string }) => api.post<{ agent: string }>(posUrl(id, pos, '/hire'), { topic }), {
    invalidate: [entKeys.all, ['agents'], qk.workspace],
    errorToast: false,
  })
}
