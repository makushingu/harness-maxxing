import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, seg } from '../api'
import type { Changelog, Health, LogsPayload, MemoryInfo, Ok, Preflight, Service, ServiceAction, Session, TokenStats, UpdateReport, UsagePayload, VersionInfo } from '../types'
import { qk } from './keys'
import { useMut } from './util'

/** Health is pushed by the bus ("health" topic) and also refreshed every 60 s as a safety net. */
export const healthQuery = () => ({ queryKey: qk.health, queryFn: () => api.get<Health>('/api/system/health') })
export function useHealth(enabled = true) {
  return useQuery({
    ...healthQuery(),
    refetchInterval: 60_000,
    enabled,
  })
}
export const servicesQuery = () => ({ queryKey: qk.system.services, queryFn: () => api.get<Service[]>('/api/system/services') })
export function useServices() {
  return useQuery(servicesQuery())
}
export function useLogs(unit: string, lines = 200) {
  return useQuery({
    queryKey: qk.system.logs(unit, lines),
    queryFn: () => api.get<LogsPayload>('/api/system/logs', { unit, lines }),
    enabled: !!unit,
  })
}
export const versionQuery = () => ({ queryKey: qk.system.version, queryFn: () => api.get<VersionInfo>('/api/system/version'), staleTime: 5 * 60_000 })
export function useVersion() {
  return useQuery({
    ...versionQuery(),
    refetchInterval: (q) => (q.state.data?.checking ? 2_000 : false),   // the server is asking GitHub
  })
}
/** Check GitHub now (the server waits for the answer) and store the result. */
export function useCheckVersion() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.get<VersionInfo>('/api/system/version', { refresh: 1 }),
    onSuccess: (v) => qc.setQueryData(qk.system.version, v),
  })
}
export function useChangelog(enabled = true) {
  return useQuery({ queryKey: qk.system.changelog, queryFn: () => api.get<Changelog>('/api/system/changelog'), enabled, staleTime: 10 * 60_000 })
}
/** Every version (Settings -> Updates). */
export function useAllUpdates() {
  return useQuery({ queryKey: [...qk.system.changelog, 'all'], queryFn: () => api.get<Changelog>('/api/system/changelog', { limit: 500 }), staleTime: 10 * 60_000 })
}
export const tokenStatsQuery = () => ({ queryKey: qk.stats.tokens, queryFn: () => api.get<TokenStats>('/api/stats/tokens'), staleTime: 30_000 })
export function useTokenStats(enabled = true) {
  return useQuery({ ...tokenStatsQuery(), enabled })
}
export function useMemory(enabled = true) {
  return useQuery({ queryKey: qk.memory, queryFn: () => api.get<MemoryInfo>('/api/memory'), enabled })
}
export function useCompactMemory() {
  return useMut(() => api.post<{ session: Session }>('/api/memory/compact'), { invalidate: [qk.sessions.all, qk.workspace] })
}
export function useUsage(enabled = true, poll = false) {
  return useQuery({ queryKey: qk.system.usage, queryFn: () => api.get<UsagePayload>('/api/usage'), enabled, staleTime: 60_000, refetchInterval: poll ? 60_000 : false })
}
export function useServiceAction() {
  return useMut(({ name, action }: { name: string; action: ServiceAction }) => api.post<Ok>(`/api/system/services/${seg(name)}/${action}`), {
    invalidate: [qk.system.services, qk.health],
  })
}
export function useUpdate() {
  return useMut(() => api.post<Ok>('/api/system/update'), { invalidate: [qk.system.version] })
}

/** Settings -> Updates: Harness updates itself while nobody is on the interface and nothing runs. */
export function useAutoUpdate() {
  return useMut((enabled: boolean) => api.put<Ok>('/api/system/auto-update', { enabled }), { invalidate: [qk.system.version] })
}

/** What the next update does to this server (simulated server-side on a throw-away copy; cached there). */
export function usePreflight(enabled: boolean, target?: string | null) {
  return useQuery({
    queryKey: [...qk.system.preflight, target ?? ''],
    queryFn: () => api.get<Preflight>('/api/system/update/preflight'),
    enabled,
    staleTime: 60_000,
    retry: false,
  })
}
/** Open the Harness session that adapts this server's changes, then updates. */
export function useUpdateAssist() {
  return useMut(() => api.post<{ session: Session }>('/api/system/update/assist'))
}
/** Open a Harness session that fixes what the last verification found broken. */
export function useUpdateFix() {
  return useMut(() => api.post<{ session: Session }>('/api/system/update/fix'))
}
/** Check now that extensions load and customization checks pass. */
export function useVerifyUpdate() {
  return useMut(() => api.post<{ report: UpdateReport }>('/api/system/update/verify'), { invalidate: [qk.system.version] })
}
