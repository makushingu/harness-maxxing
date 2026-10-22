import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import type { Ok, TelegramLinkStart, TelegramLinkState, TelegramSettings, TelegramStatus, TelegramSyncResult, TelegramTokenResult } from '../types'
import { qk } from './keys'
import { useMut } from './util'

export const telegramQuery = () => ({ queryKey: qk.telegram.status, queryFn: () => api.get<TelegramStatus>('/api/telegram') })
export function useTelegram() {
  return useQuery(telegramQuery())
}
/** Polls every 2 s while `poll` is true (link waiting for /start <code>). */
export function useTelegramLink(poll: boolean) {
  return useQuery({
    queryKey: qk.telegram.link,
    queryFn: () => api.get<TelegramLinkState>('/api/telegram/link'),
    enabled: poll,
    refetchInterval: poll ? 2000 : false,
  })
}
const inv = [qk.telegram.all, qk.onboarding] as const
export function useTelegramToken() {
  return useMut((token: string) => api.post<TelegramTokenResult>('/api/telegram/token', { token }), { invalidate: inv, errorToast: false })
}
export function useTelegramLinkStart() {
  return useMut(() => api.post<TelegramLinkStart>('/api/telegram/link'), {})
}
export function useTelegramSync() {
  return useMut(() => api.post<TelegramSyncResult>('/api/telegram/sync'), { invalidate: [...inv, qk.workspace] })
}
export function useTelegramSettings() {
  return useMut((b: Partial<TelegramSettings>) => api.put<Ok>('/api/telegram/settings', b), {
    optimistic: (b) => [{ key: qk.telegram.status, update: (s: TelegramStatus) => ({ ...s, settings: { ...s.settings, ...b } }) }],
    invalidate: inv,
  })
}
export function useTelegramTest() {
  return useMut(() => api.post<Ok>('/api/telegram/test'), {})
}
export function useTelegramUnlink() {
  return useMut(() => api.del<Ok>('/api/telegram'), { invalidate: inv })
}
