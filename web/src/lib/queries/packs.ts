import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import type { Pack, PackInstallResult } from '../types'
import { qk } from './keys'
import { useMut } from './util'

/** Starter packs (ready-made projects), installed or not. The key sits under `workspace`, so the live bus refreshes it. */
export function usePacks() {
  return useQuery({ queryKey: qk.packs, queryFn: () => api.get<{ packs: Pack[] }>('/api/packs') })
}
export function useInstallPack() {
  return useMut((id: string) => api.post<PackInstallResult>(`/api/packs/${encodeURIComponent(id)}/install`), { invalidate: [qk.workspace, qk.packs, qk.crons.all] })
}
