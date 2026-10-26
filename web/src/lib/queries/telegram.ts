import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import type { Ok, TelegramLinkStart, TelegramLinkState, TelegramSettings, TelegramStatus, TelegramSyncResult, TelegramTestResult, TelegramTokenResult } from '../types'
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
  const qc = useQueryClient()
  return useMut(() => api.post<TelegramLinkStart>('/api/telegram/link'), {
    // the new code shows at once (the status query carries it, so leaving the page does not lose it)
    onSuccess: (l) => {
      const link = { ...l, expired: false }
      qc.setQueryData(qk.telegram.status, (s: TelegramStatus | undefined) => (s ? { ...s, linking: true, link } : s))
      qc.setQueryData(qk.telegram.link, (s: TelegramLinkState | undefined) => ({ linked: false, chat: null, ...s, pending: link }))
    },
    invalidate: [qk.telegram.all],
  })
}
/** Removes the webhook of the bot being saved (the token is then saved again). */
export function useTelegramRemoveWebhook() {
  return useMut((token: string) => api.post<Ok>('/api/telegram/webhook/remove', { token }), { errorToast: false })
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
  return useMut(() => api.post<TelegramTestResult>('/api/telegram/test'), { invalidate: [qk.telegram.status] })
}
export function useTelegramUnlink() {
  return useMut(() => api.del<Ok>('/api/telegram'), { invalidate: inv })
}
