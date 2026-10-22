import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import type { Ok, PcBrowser, PcOs, PcPairing, PcStatus } from '../types'
import { qk } from './keys'
import { useMut } from './util'

/** Browser of my PC. Polls every 3 s while a download or a PC waits, else every 15 s (online / in use). */
export function usePc() {
  return useQuery({
    queryKey: qk.pc,
    queryFn: () => api.get<PcStatus>('/api/pc'),
    refetchInterval: (q) => {
      const s = q.state.data
      if (s && !s.available && !s.device) return false
      return s?.pairing || s?.candidate ? 3000 : 15000
    },
  })
}
export function usePcPairing() {
  return useMut((b: { browser: PcBrowser; os: PcOs; autostart: boolean }) => api.post<PcPairing>('/api/pc/pairing', b), { invalidate: [qk.pc] })
}
export function usePcConfirm() {
  return useMut((b: { id: string; ok: boolean }) => api.post<Ok>('/api/pc/confirm', b), {
    optimistic: () => [{ key: qk.pc, update: (s: PcStatus) => ({ ...s, candidate: null }) }],
    invalidate: [qk.pc, ['mcp']],
  })
}
export function usePcSettings() {
  return useMut((b: { idle_min: number }) => api.put<{ idle_min: number }>('/api/pc/settings', b), {
    optimistic: (b) => [{ key: qk.pc, update: (s: PcStatus) => ({ ...s, settings: { ...s.settings, ...b } }) }],
    invalidate: [qk.pc],
  })
}
export function usePcStop() {
  return useMut(() => api.post<Ok>('/api/pc/stop'), {
    optimistic: () => [{ key: qk.pc, update: (s: PcStatus) => ({ ...s, browser_running: false, mcp_running: false }) }],
    invalidate: [qk.pc],
  })
}
export function usePcTest() {
  return useMut(() => api.post<{ ok: boolean; text: string }>('/api/pc/test'), { invalidate: [qk.pc] })
}
export function usePcWipe() {
  return useMut(() => api.post<Ok>('/api/pc/wipe'), { invalidate: [qk.pc] })
}
export function usePcUnpair() {
  return useMut(() => api.del<Ok>('/api/pc'), {
    optimistic: () => [{ key: qk.pc, update: (s: PcStatus) => ({ ...s, device: null, online: false, browser_running: false }) }],
    invalidate: [qk.pc, ['mcp']],
  })
}
