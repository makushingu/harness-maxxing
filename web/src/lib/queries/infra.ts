import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import type { InfraView } from '../types'
import { useMut } from './util'

// Infra page (server/maxxing/infra): one snapshot refreshed in the background; the bus topic `infra` says when.
export const infraKeys = { all: ['infra'] as const }

export function useInfra(enabled = true) {
  return useQuery({
    queryKey: infraKeys.all,
    queryFn: () => api.get<InfraView>('/api/infra'),
    enabled,
    staleTime: 30_000,
    refetchInterval: (q) => (q.state.data?.refreshing ? 2000 : false),
  })
}
export function useInfraRefresh() {
  return useMut(() => api.post<{ started: boolean }>('/api/infra/refresh', {}), { invalidate: [infraKeys.all] })
}
export function useInfraAnnotate() {
  return useMut((b: { id: string; project?: string; note?: string; hidden?: boolean }) => api.post('/api/infra/annotate', b), {
    invalidate: [infraKeys.all],
  })
}
export type InfraConnectIn = { id?: string; host?: string; user?: string; port?: number; label?: string }
export type InfraConnectOut = { connected: boolean; name?: string; label?: string; via?: string; message?: string; public_key?: string; command?: string }
export function useInfraConnect() {
  return useMut((b: InfraConnectIn) => api.post<InfraConnectOut>('/api/infra/servers/connect', b), {
    invalidate: [infraKeys.all],
  })
}
export function useInfraServerRename() {
  return useMut((b: { name: string; label: string }) => api.post('/api/infra/servers/rename', b), { invalidate: [infraKeys.all] })
}
export function useInfraServerRemove() {
  return useMut((b: { name: string }) => api.post('/api/infra/servers/remove', b), { invalidate: [infraKeys.all] })
}
export function useInfraDomainAdd() {
  return useMut((b: { name: string }) => api.post<{ name: string }>('/api/infra/domains', b), { invalidate: [infraKeys.all] })
}
export function useInfraDomainRemove() {
  return useMut((b: { name: string }) => api.post('/api/infra/domains/remove', b), { invalidate: [infraKeys.all] })
}
