import { useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { api, seg } from '../api'
import type {
  CreateSessionBody,
  Ok,
  PatchSessionBody,
  SendMessageBody,
  SendMessageResult,
  Session,
  SessionEventsBackPage,
  SessionSearchHit,
  UploadResult,
} from '../types'
import { qk, unlessBus } from './keys'
import { useMut } from './util'

export const sessionsQuery = (path?: string | null, archived = false) => ({
  queryKey: qk.sessions.list(path, archived),
  queryFn: () => api.get<Session[]>('/api/sessions', { path: path ?? undefined, archived }),
})
export const sessionQuery = (id: string) => ({ queryKey: qk.sessions.one(id), queryFn: () => api.get<Session>(`/api/sessions/${seg(id)}`) })

/** Warms the live sessions list (the Sessions page and its tree read this key first). */
export function prefetchSessions(qc: QueryClient) {
  return qc.prefetchQuery(sessionsQuery(undefined, false))
}

export function useSessions(path?: string | null, archived = false, enabled = true) {
  return useQuery({ ...sessionsQuery(path, archived), enabled })
}

export function useSession(id: string | null | undefined) {
  return useQuery({ ...sessionQuery(id || ''), enabled: !!id })
}

export function useSessionSearch(q: string) {
  return useQuery({
    queryKey: qk.sessions.search(q),
    queryFn: ({ signal }) => api.get<SessionSearchHit[]>('/api/sessions/search', { q }, { signal }),
    enabled: q.trim().length >= 2,
    staleTime: 10_000,
  })
}

/** Fields that move on every metadata write of a running turn (tokens, cost, preview text, timestamps). */
const TICKING = new Set<string>(['updated', 'cost_usd', 'context_tokens', 'context_window', 'real_model', 'last_text'])
const listWrites = new Map<string, number>()
const LIST_TICK_MS = 2_000

/** Writes a fresh Session payload into the caches (list + one) without refetching. The lists (the whole tree
 *  regroups when one changes) take a running turn's ticking fields at most every 2 s; any other change at once. */
export function useSetSessionCache() {
  const qc = useQueryClient()
  return (s: Session) => {
    const prev = qc.getQueryData<Session>(qk.sessions.one(s.id))
    // queue_items is a new array on every payload: keep the cached one while it says the same (no re-render)
    if (prev?.queue_items && s.queue_items && JSON.stringify(prev.queue_items) === JSON.stringify(s.queue_items)) s = { ...s, queue_items: prev.queue_items }
    qc.setQueryData(qk.sessions.one(s.id), s)
    const now = Date.now()
    const ticking = !!prev && (Object.keys(s) as (keyof Session)[]).every((k) => prev[k] === s[k] || TICKING.has(k))
    if (ticking && now - (listWrites.get(s.id) || 0) < LIST_TICK_MS) return
    listWrites.set(s.id, now)
    qc.setQueriesData<Session[]>({ queryKey: ['sessions', 'list'] }, (old) =>
      old ? old.map((x) => (x.id === s.id ? s : x)) : old,
    )
  }
}

// Every session write below is announced on the bus by the server (`sessions`, plus `workspace` when the tree's
// counters move): the bus refetches the lists and the tree. The mutations only write what they know into the caches,
// and invalidate themselves only while the bus is down.
const inv = unlessBus([qk.sessions.all, qk.workspace])
const invSessions = unlessBus([qk.sessions.all])

/** Puts a Session the server just returned in its place: its own cache, and the lists it belongs to (added to them,
 *  moved out of them when archived or moved to another topic, updated otherwise). */
export function placeSession(qc: QueryClient, s: Session) {
  qc.setQueryData(qk.sessions.one(s.id), s)
  for (const [key, list] of qc.getQueriesData<Session[]>({ queryKey: ['sessions', 'list'] })) {
    if (!list) continue
    const [, , path, archived] = key as ReturnType<typeof qk.sessions.list>
    const belongs = archived === s.archived && (path === null || path === s.path)
    const at = list.findIndex((x) => x.id === s.id)
    if (belongs) qc.setQueryData(key, at < 0 ? [s, ...list] : list.map((x) => (x.id === s.id ? s : x)))
    else if (at >= 0) qc.setQueryData(key, list.filter((x) => x.id !== s.id))
  }
}

/** Takes a deleted session out of the lists (its column learns it from its stream). */
function dropSession(qc: QueryClient, id: string) {
  qc.setQueriesData<Session[]>({ queryKey: ['sessions', 'list'] }, (old) => (old?.some((x) => x.id === id) ? old.filter((x) => x.id !== id) : old))
}

/** Create a session and seed the caches with the answer (no flash of "unknown session"). */
export function useCreateSession() {
  const qc = useQueryClient()
  return useMut((b: CreateSessionBody) => api.post<Session>('/api/sessions', b), { onSuccess: (s) => placeSession(qc, s), invalidate: inv })
}
/** Fields a PATCH changes as they are: shown at once (optimistic), the server's answer then replaces them. */
const INSTANT_FIELDS = ['title', 'model', 'archived', 'notify', 'plan_mode', 'favorite'] as const

export function usePatchSession() {
  const qc = useQueryClient()
  return useMut(({ id, ...b }: PatchSessionBody & { id: string }) => api.patch<Session>(`/api/sessions/${seg(id)}`, b), {
    optimistic: ({ id, ...b }) => {
      const change: Partial<Session> = {}
      for (const k of INSTANT_FIELDS) if (b[k] !== undefined) Object.assign(change, { [k]: b[k] })
      if (!Object.keys(change).length) return []
      return [
        { key: qk.sessions.one(id), update: (s: Session) => ({ ...s, ...change }) },
        { key: ['sessions', 'list'], update: (l: Session[]) => l.map((x) => (x.id === id ? { ...x, ...change } : x)) },
      ]
    },
    onSuccess: (s) => placeSession(qc, s),
    invalidate: inv,
  })
}
export function useDeleteSession() {
  const qc = useQueryClient()
  return useMut((id: string) => api.del<Ok>(`/api/sessions/${seg(id)}`), { onSuccess: (_r, id) => dropSession(qc, id), invalidate: inv })
}
export function useSendMessage() {
  const set = useSetSessionCache()
  return useMut(({ id, ...b }: SendMessageBody & { id: string }) => api.post<SendMessageResult>(`/api/sessions/${seg(id)}/messages`, b), {
    onSuccess: (r) => set(r.session),
  })
}
export function useClearQueue() {
  return useMut((id: string) => api.del<Ok>(`/api/sessions/${seg(id)}/queue`), { invalidate: invSessions })
}
/** Side question: Claude answers about the session without interrupting it (nothing is saved in the session). */
export function useAskAside() {
  return useMut(({ id, question }: { id: string; question: string }) => api.post<{ answer: string; cost_usd: number; duration_ms: number }>(`/api/sessions/${seg(id)}/ask`, { question }), {
    errorToast: false,
  })
}
/** Edit: takes the queued messages out of the queue (they come back in the composer). */
export function useTakeQueue() {
  const set = useSetSessionCache()
  return useMut((id: string) => api.post<{ messages: { text: string; attachments: string[] }[]; session: Session }>(`/api/sessions/${seg(id)}/queue/take`), {
    onSuccess: (r) => set(r.session),
    invalidate: invSessions,
  })
}
/** Steer: the queued messages run now, the current turn is cut short and Claude goes on with them. */
export function useSteerSession() {
  const set = useSetSessionCache()
  return useMut((id: string) => api.post<{ steered: boolean; interrupted: boolean; session: Session }>(`/api/sessions/${seg(id)}/steer`), {
    onSuccess: (r) => set(r.session),
    invalidate: invSessions,
  })
}
/** Plan mode: the user validates the plan - plan mode goes off and Claude implements it (`text` is shown). */
export function useApprovePlan() {
  const set = useSetSessionCache()
  return useMut(({ id, text }: { id: string; text: string }) => api.post<SendMessageResult>(`/api/sessions/${seg(id)}/plan/approve`, { text }), {
    onSuccess: (r) => set(r.session),
  })
}
/** Hide (or show again) a user message of the thread (`at` = its time). A plain call, not a mutation hook: several
 *  hides / undos can be in flight at once and each keeps its own outcome (log.ts updates the thread at once). */
export function hideMessage(id: string, at: number, hidden: boolean) {
  return api.post<Ok>(`/api/sessions/${seg(id)}/hide`, { at, hidden })
}
export function useStopSession() {
  return useMut((id: string) => api.post<Ok>(`/api/sessions/${seg(id)}/stop`), { invalidate: invSessions })
}
export function useCompactSession() {
  return useMut((id: string) => api.post<Ok>(`/api/sessions/${seg(id)}/compact`), { invalidate: invSessions })
}
export function useHandoffSession() {
  const qc = useQueryClient()
  return useMut((id: string) => api.post<Session>(`/api/sessions/${seg(id)}/handoff`), { onSuccess: (s) => placeSession(qc, s), invalidate: inv })
}
/** Read at once on screen (the unread mark goes away before the request); the bus then refreshes the tree's counters. */
export function useMarkSeen() {
  return useMut((id: string) => api.post<Ok>(`/api/sessions/${seg(id)}/seen`), {
    optimistic: (id) => [
      { key: qk.sessions.one(id), update: (s: Session) => ({ ...s, unread: false }) },
      { key: ['sessions', 'list'], update: (l: Session[]) => l.map((x) => (x.id === id && x.unread ? { ...x, unread: false } : x)) },
    ],
    invalidate: inv,
    errorToast: false,
  })
}
export function useUpload() {
  return useMut(({ path, files }: { path: string; files: File[] }) => api.upload<UploadResult>('/api/uploads', files, { path }))
}

/* ---------------------------------------------------------------- Sessions page helpers */

/** Last events of a session log (read backwards by the server): how a thread opens. */
export function fetchTail(id: string, n = 200, signal?: AbortSignal): Promise<SessionEventsBackPage> {
  return api.get<SessionEventsBackPage>(`/api/sessions/${seg(id)}/events`, { tail: n }, { signal })
}

/** Events of a session's first page (the thread's initial load). */
export const TAIL_EVENTS = 100
const earlyTails = new Map<string, { p: Promise<SessionEventsBackPage>; at: number }>()
/** Starts loading a session's tail before the Sessions page is there (app boot, see lib/boot.ts), or before it
 *  comes in front (Maxxing mode). A tail still fresh is kept; an old one is loaded again. */
export function prefetchTail(id: string) {
  const e = earlyTails.get(id)
  if (e && Date.now() - e.at < 10_000) return
  const p = fetchTail(id, TAIL_EVENTS)
  p.catch(() => undefined)
  earlyTails.set(id, { p, at: Date.now() })
}
/** The tail started by `prefetchTail` (consumed once, and only while recent: later loads always fetch; the live
 *  stream resumes from its `next` offset, so nothing is missed either way). */
export function takeEarlyTail(id: string): Promise<SessionEventsBackPage> | undefined {
  const e = earlyTails.get(id)
  earlyTails.delete(id)
  return e && Date.now() - e.at < 15_000 ? e.p : undefined
}

/** Events strictly before byte `before` ("Show earlier messages"). `reset` = the log was rewritten. */
export function fetchBefore(id: string, before: number, limit = 200, signal?: AbortSignal): Promise<SessionEventsBackPage> {
  return api.get<SessionEventsBackPage>(`/api/sessions/${seg(id)}/events`, { before, limit }, { signal })
}

/** Upload one attachment with progress (XHR: fetch has no upload progress). Resolves to the saved file. */
export function uploadAttachment(
  topicPath: string,
  file: File,
  onProgress?: (loaded: number, total: number) => void,
  signal?: AbortSignal,
): Promise<UploadResult['files'][number]> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `/api/uploads?path=${encodeURIComponent(topicPath)}`)
    xhr.setRequestHeader('X-Maxxing', '1')
    xhr.withCredentials = true
    xhr.upload.onprogress = (e) => onProgress?.(e.loaded, e.total || file.size)
    xhr.onload = () => {
      let data: { files?: UploadResult['files']; message?: string; error?: string } = {}
      try {
        data = JSON.parse(xhr.responseText || '{}')
      } catch {
        /* ignore */
      }
      if (xhr.status >= 200 && xhr.status < 300 && data.files?.[0]) resolve(data.files[0])
      else reject(new Error(data.message || data.error || `HTTP ${xhr.status}`))
    }
    xhr.onerror = () => reject(new Error('Network error'))
    xhr.onabort = () => reject(new DOMException('Aborted', 'AbortError'))
    signal?.addEventListener('abort', () => xhr.abort())
    const fd = new FormData()
    fd.append('file', file, file.name)
    xhr.send(fd)
  })
}

/** useSession seeded from any cached list (instant header, refreshed in the background). */
export function useSessionSeeded(id: string | null | undefined) {
  const qc = useQueryClient()
  return useQuery({
    ...sessionQuery(id || ''),
    enabled: !!id,
    initialData: () => {
      if (!id) return undefined
      for (const [, list] of qc.getQueriesData<Session[]>({ queryKey: ['sessions', 'list'] })) {
        const hit = list?.find((s) => s.id === id)
        if (hit) return hit
      }
      return undefined
    },
    initialDataUpdatedAt: 0,
  })
}
