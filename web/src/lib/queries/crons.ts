import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, errorMessage, isApiError, seg } from '../api'
import { toast } from '@/components/ui/toast'
import type { Cron, CronInput, CronPreview, CronRun, CronsPayload, Ok } from '../types'
import { qk } from './keys'
import { useMut } from './util'

export const cronsQuery = () => ({ queryKey: qk.crons.list, queryFn: () => api.get<CronsPayload>('/api/crons') })
export function useCrons() {
  return useQuery(cronsQuery())
}
export function useCron(id: string | null | undefined) {
  return useQuery({ queryKey: [...qk.crons.all, 'one', id || ''], queryFn: () => api.get<Cron>(`/api/crons/${seg(id!)}`), enabled: !!id })
}
export const cronRunsQuery = (cronId?: string | null, limit = 50) => ({
  queryKey: qk.crons.runs(cronId, limit),
  queryFn: () => api.get<CronRun[]>('/api/crons/runs', { cron_id: cronId ?? undefined, limit }),
})
export function useCronRuns(cronId?: string | null, limit = 50) {
  return useQuery(cronRunsQuery(cronId, limit))
}
/** Debounce `schedule` in the caller; previous data is kept while typing (no flicker). */
export function useCronPreview(schedule: string) {
  return useQuery({
    queryKey: qk.crons.preview(schedule),
    queryFn: () => api.get<CronPreview>('/api/crons/preview', { schedule }),
    enabled: schedule.trim().length > 0,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  })
}
const inv = [qk.crons.all] as const
export function useCreateCron() {
  return useMut((b: CronInput) => api.post<Cron>('/api/crons', b), { invalidate: inv, errorToast: false })
}
export function usePatchCron() {
  return useMut(({ id, ...b }: CronInput & { id: string }) => api.patch<Cron>(`/api/crons/${seg(id)}`, b), { invalidate: inv })
}
export function useDeleteCron() {
  return useMut((id: string) => api.del<Ok>(`/api/crons/${seg(id)}`), { invalidate: inv })
}
export function useRunCron() {
  return useMut((id: string) => api.post<Ok>(`/api/crons/${seg(id)}/run`), { invalidate: inv })
}

/** Create (no id) or update (id) from the job editor — errors are shown inline by the form. */
export function useSaveCron() {
  return useMut(
    ({ id, ...b }: CronInput & { id?: string }) => (id ? api.patch<Cron>(`/api/crons/${seg(id)}`, b) : api.post<Cron>('/api/crons', b)),
    { invalidate: inv, errorToast: false },
  )
}

/** Patch the cached job immediately (enabled switch…), rolled back on error. */
export function usePatchCronOptimistic() {
  const qc = useQueryClient()
  return useMut(({ id, ...b }: CronInput & { id: string }) => api.patch<Cron>(`/api/crons/${seg(id)}`, b), {
    onMutate: async ({ id, ...b }) => {
      await qc.cancelQueries({ queryKey: qk.crons.list })
      const prev = qc.getQueryData<CronsPayload>(qk.crons.list)
      if (prev) qc.setQueryData<CronsPayload>(qk.crons.list, { ...prev, jobs: prev.jobs.map((j) => (j.id === id ? { ...j, ...b } : j)) })
      return { prev }
    },
    onError: (_e, _v, ctx) => {
      const c = ctx as { prev?: CronsPayload } | undefined
      if (c?.prev) qc.setQueryData(qk.crons.list, c.prev)
    },
    invalidate: inv,
  })
}

/** "Run now": marks the job as running right away; 409 already_running → info toast (not an error). */
export function useRunCronNow(messages: { started: string; already: string }) {
  const qc = useQueryClient()
  const mark = (id: string) => {
    const prev = qc.getQueryData<CronsPayload>(qk.crons.list)
    if (prev) qc.setQueryData<CronsPayload>(qk.crons.list, { ...prev, jobs: prev.jobs.map((j) => (j.id === id ? { ...j, running: true } : j)) })
  }
  return useMut((id: string) => api.post<Ok>(`/api/crons/${seg(id)}/run`), {
    errorToast: false,
    onSuccess: (_d, id) => {
      mark(id)
      toast.success(messages.started)
    },
    onError: (e, id) => {
      if (isApiError(e, 'already_running')) {
        mark(id)
        toast.info(messages.already)
      } else toast.error(errorMessage(e))
    },
    invalidate: [['crons', 'runs']],
  })
}
