import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import type { JarvisSettings, JarvisStatus } from '../types'
import { useMut } from './util'

// Jarvis (Settings -> Features -> jarvis_feature): its conversation, work board and settings (server jarvis.py).
// The bus topic "jarvis" refreshes it (a report came, the board moved, a new conversation).
const jarvisKey = ['jarvis'] as const

export function useJarvis(enabled = true) {
  return useQuery({ queryKey: jarvisKey, queryFn: () => api.get<JarvisStatus>('/api/jarvis'), enabled, refetchInterval: 60_000 })
}

/** The page opens: its conversation (made the first time). */
export function useOpenJarvis() {
  return useMut(() => api.post<JarvisStatus>('/api/jarvis/open'), { invalidate: [jarvisKey] })
}
export function useNewJarvisConversation() {
  return useMut(() => api.post<JarvisStatus>('/api/jarvis/new'), { invalidate: [jarvisKey] })
}
export function useJarvisSettings() {
  return useMut((s: Partial<JarvisSettings>) => api.put<JarvisStatus>('/api/jarvis/settings', s), { invalidate: [jarvisKey, ['workspace'], ['sessions']] })
}
export function useCloseJarvisWork() {
  return useMut((id: number) => api.post<JarvisStatus>(`/api/jarvis/work/${id}/close`), { invalidate: [jarvisKey] })
}
export function useJarvisBrief() {
  return useMut(() => api.post<JarvisStatus>('/api/jarvis/brief'), { invalidate: [jarvisKey] })
}
export function useJarvisDream() {
  return useMut(() => api.post<{ session: { id: string } }>('/api/jarvis/dream'), { invalidate: [jarvisKey] })
}
