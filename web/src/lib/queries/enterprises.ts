import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, seg } from '../api'
import type { DecisionItem, Enterprise, EnterpriseAbout, EnterpriseBuilt, EnterpriseEscalation, EnterpriseInput, DeskMessage, DeskSettingsPatch, DeskSuggestion, EnterpriseDesk, EnterpriseInsights, EnterpriseOverview, EnterpriseWorker, EnterprisePatch, EnterpriseProfile, EnterpriseReport, EnterpriseReportDoc, EnterpriseRequest, EnterpriseSummary, EnterpriseTemplate, InboxItem, Ok, PositionInput, PositionPatch } from '../types'
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
  overview: (id: string) => ['enterprises', 'overview', id] as const,
  reports: (id: string) => ['enterprises', 'reports', id] as const,
  report: (id: string, name: string) => ['enterprises', 'reports', id, name] as const,
  requests: (id: string) => ['enterprises', 'requests', id] as const,
  escalations: (id: string) => ['enterprises', 'escalations', id] as const,
  about: (id: string) => ['enterprises', 'about', id] as const,
  profile: (id: string) => ['enterprises', 'profile', id] as const,
  insights: (id: string) => ['enterprises', 'insights', id] as const,
  desk: (id: string) => ['enterprises', 'desk', id] as const,
  conversation: (id: string, conv: string) => ['enterprises', 'desk', id, conv] as const,
  suggestions: (id: string) => ['enterprises', 'suggestions', id] as const,
  workers: (id: string) => ['enterprises', 'workers', id] as const,
}

const base = (id: string, sub = '') => `/api/enterprises/${seg(id)}${sub}`
const posUrl = (id: string, pos: string, sub = '') => base(id, `/positions/${seg(pos)}${sub}`)

/** Route of an enterprise: its org chart, or one of its tabs. */
export const enterpriseRoute = (id: string, tab = '') => `/enterprises/${id}${tab && tab !== 'chart' ? `/${tab}` : ''}`

export function useEnterprises(enabled = true) {
  return useQuery({ queryKey: entKeys.list, queryFn: () => api.get<{ enterprises: EnterpriseSummary[] }>('/api/enterprises').then((r) => r.enterprises), enabled })
}
export const enterpriseQuery = (id: string) => ({ queryKey: entKeys.one(id), queryFn: () => api.get<Enterprise>(base(id)) })
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
/** `409 has_reports` = the position leads others: the caller asks where they go and sends `reparent_to` (a position id or "owner"). */
export function useDeletePosition() {
  return useMut(({ id, pos, reparent_to }: { id: string; pos: string; reparent_to?: string }) => api.del<Ok>(`${posUrl(id, pos)}${reparent_to ? `?reparent_to=${encodeURIComponent(reparent_to)}` : ''}`), { invalidate: [entKeys.all], errorToast: false })
}
/** Creates the agent in `topic` (a topic path, projects/<p>/topics/<t>) and seats it; the agent sets itself up in its conversation. */
export function useHirePosition() {
  return useMut(({ id, pos, topic, template }: { id: string; pos: string; topic: string; template?: string }) => api.post<{ agent: string }>(posUrl(id, pos, '/hire'), { topic, template }), {
    invalidate: [entKeys.all, ['agents'], qk.workspace],
    errorToast: false,
  })
}

// ---- Overview, reports, requests, escalations, knowledge. The bus topic `enterprises:<slug>` refreshes them all (keys.ts).

export function useEnterpriseOverview(id: string | null) {
  return useQuery({ queryKey: entKeys.overview(id || ''), queryFn: () => api.get<EnterpriseOverview>(base(id!, '/overview')), enabled: !!id })
}
export function useEnterpriseReports(id: string | null) {
  return useQuery({ queryKey: entKeys.reports(id || ''), queryFn: () => api.get<{ items: EnterpriseReport[] }>(base(id!, '/reports')).then((r) => r.items), enabled: !!id })
}
export function useEnterpriseReport(id: string | null, name: string | null) {
  return useQuery({ queryKey: entKeys.report(id || '', name || ''), queryFn: () => api.get<EnterpriseReportDoc>(base(id!, `/reports/${seg(name!)}`)), enabled: !!id && !!name })
}
/** Builds one report now (`built: false` = nothing to report yet). */
export function useBuildReport() {
  return useMut(({ id, kind }: { id: string; kind: EnterpriseReport['kind'] }) => api.post<EnterpriseBuilt>(base(id, '/reports'), { kind }), {
    invalidate: [['enterprises', 'reports'], ['enterprises', 'overview']],
  })
}
export function useEnterpriseRequests(id: string | null) {
  return useQuery({ queryKey: entKeys.requests(id || ''), queryFn: () => api.get<{ items: EnterpriseRequest[] }>(base(id!, '/requests')).then((r) => r.items), enabled: !!id })
}
export function useDecideRequest() {
  return useMut(({ id, rid, decision, reason }: { id: string; rid: string; decision: 'allow' | 'deny'; reason?: string }) => api.post<EnterpriseRequest>(base(id, `/requests/${seg(rid)}`), { decision, reason: reason || undefined }), {
    invalidate: [['enterprises', 'requests'], ['enterprises', 'overview'], ['enterprises', 'decisions']],
  })
}
export function useEnterpriseEscalations(id: string | null) {
  return useQuery({ queryKey: entKeys.escalations(id || ''), queryFn: () => api.get<{ items: EnterpriseEscalation[] }>(base(id!, '/escalations')).then((r) => r.items), enabled: !!id })
}
export function useAnswerEscalation() {
  return useMut(({ id, esc, text }: { id: string; esc: string; text: string }) => api.post<EnterpriseEscalation>(base(id, `/escalations/${seg(esc)}/answer`), { text }), {
    invalidate: [['enterprises', 'escalations'], ['enterprises', 'overview'], ['enterprises', 'decisions']],
  })
}
/** The enterprise's CLAUDE.md (what every occupant reads first). */
export function useEnterpriseAbout(id: string | null) {
  return useQuery({ queryKey: entKeys.about(id || ''), queryFn: () => api.get<EnterpriseAbout>(base(id!, '/about')), enabled: !!id })
}
export function usePutEnterpriseAbout() {
  const qc = useQueryClient()
  return useMut(({ id, text }: { id: string; text: string }) => api.put<EnterpriseAbout>(base(id, '/about'), { text }), {
    onSuccess: (r, { id }) => qc.setQueryData(entKeys.about(id), r),
    errorToast: false,
  })
}
/** The company profile: what customers may hear (products, hours, terms, contact, FAQ). */
export function useEnterpriseProfile(id: string | null) {
  return useQuery({ queryKey: entKeys.profile(id || ''), queryFn: () => api.get<EnterpriseProfile>(base(id!, '/profile')), enabled: !!id })
}
/** `200 {profile}` applied, or `202 {request}` when the change waits for the owner's decision (see requests). */
export function usePutEnterpriseProfile() {
  const qc = useQueryClient()
  return useMut(({ id, profile }: { id: string; profile: EnterpriseProfile }) => api.put<{ profile?: EnterpriseProfile; request?: EnterpriseRequest }>(base(id, '/profile'), profile), {
    onSuccess: (r, { id }) => {
      if (r.profile) qc.setQueryData(entKeys.profile(id), r.profile)
    },
    errorToast: false,
  })
}
export function useEnterpriseInsights(id: string | null) {
  return useQuery({ queryKey: entKeys.insights(id || ''), queryFn: () => api.get<EnterpriseInsights>(base(id!, '/insights')), enabled: !!id, retry: false })
}

// ---- Front desk (settings, conversations, insights, suggested FAQ entries) and workers

/** The desk's status: settings, the public link, the occupants that are not Protected, the conversations (newest first). */
export function useEnterpriseDesk(id: string | null) {
  return useQuery({ queryKey: entKeys.desk(id || ''), queryFn: () => api.get<EnterpriseDesk>(base(id!, '/desk')), enabled: !!id })
}
export function useDeskConversation(id: string | null, conv: string | null) {
  return useQuery({ queryKey: entKeys.conversation(id || '', conv || ''), queryFn: () => api.get<{ id: string; messages: DeskMessage[] }>(base(id!, `/desk/${seg(conv!)}`)).then((r) => r.messages), enabled: !!id && !!conv })
}
export function useDeleteDeskConversation() {
  return useMut(({ id, conv }: { id: string; conv: string }) => api.del<Ok>(base(id, `/desk/${seg(conv)}`)), { invalidate: [['enterprises', 'desk']] })
}
/** Only the desk's settings go (the server merges partial settings). `400 unprotected_occupants` when going live: the form shows it. */
export function useSaveDeskSettings() {
  const put = usePutEnterprise()
  return useMut(({ id, desk }: { id: string; desk: DeskSettingsPatch }) => api.patch<Enterprise>(base(id), { settings: { desk } }), { onSuccess: put, invalidate: [['enterprises', 'desk'], entKeys.list], errorToast: false })
}
/** Makes the public link (or replaces it: the old one stops working). */
export function useDeskLink() {
  return useMut(({ id, regenerate }: { id: string; regenerate?: boolean }) => api.post<{ token: string; path: string }>(base(id, '/desk/link'), { regenerate: !!regenerate }), { invalidate: [['enterprises', 'desk'], entKeys.all], errorToast: false })
}
/** Builds this week's table now. */
export function useRunInsights() {
  const qc = useQueryClient()
  return useMut(({ id }: { id: string }) => api.post<{ built: boolean; insights: EnterpriseInsights }>(base(id, '/insights')), {
    onSuccess: (r, { id }) => qc.setQueryData(entKeys.insights(id), r.insights),
    invalidate: [['enterprises', 'suggestions']],
  })
}
export function useDeskSuggestions(id: string | null) {
  return useQuery({ queryKey: entKeys.suggestions(id || ''), queryFn: () => api.get<{ items: DeskSuggestion[] }>(base(id!, '/profile/suggestions')).then((r) => r.items), enabled: !!id })
}
/** Accept (with the answer to publish; the question may be reworded) adds a FAQ entry to the profile; dismiss drops it. */
export function useDecideSuggestion() {
  return useMut(({ id, sid, action, q, a }: { id: string; sid: string; action: 'accept' | 'dismiss'; q?: string; a?: string }) => api.post<DeskSuggestion>(base(id, `/profile/suggestions/${seg(sid)}`), { action, q, a }), {
    invalidate: [['enterprises', 'suggestions'], ['enterprises', 'profile'], ['enterprises', 'decisions']],
    errorToast: false,
  })
}
/** The workers of a position (live first as the server sends them, newest first). */
export function useEnterpriseWorkers(id: string | null) {
  return useQuery({ queryKey: entKeys.workers(id || ''), queryFn: () => api.get<{ items: EnterpriseWorker[] }>(base(id!, '/workers')).then((r) => r.items), enabled: !!id })
}
export function useStopWorker() {
  return useMut(({ id, wid }: { id: string; wid: string }) => api.del<Ok>(base(id, `/workers/${seg(wid)}`)), { invalidate: [['enterprises', 'workers'], ['agents']] })
}

/** The enterprise as a zip (a download). */
export const enterpriseExportUrl = (id: string) => base(id, '/export')

/** Import an exported zip as a new enterprise (the raw bytes of the file); `skipped` lists what was left out. */
export function useImportEnterprise() {
  const put = usePutEnterprise()
  return useMut((file: File) => api.post<Enterprise & { skipped?: { file: string; reason: string }[] }>('/api/enterprises/import', file), { onSuccess: put, invalidate: inv })
}
